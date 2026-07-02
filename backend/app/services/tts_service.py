import asyncio
import json
import logging
from typing import AsyncGenerator, Optional
from urllib.parse import urlencode

import aiohttp
import websockets

logger = logging.getLogger(__name__)

DG_TTS_WS_URL = "wss://api.deepgram.com/v1/speak"
DG_TTS_REST_URL = "https://api.deepgram.com/v1/speak"


class TTSService:
    def __init__(self, api_key: str):
        self.api_key = api_key

    # ──────────────────────────────────────────
    # Legacy REST — returns full audio bytes
    # Used by phone webhook pipeline
    # ──────────────────────────────────────────
    async def synthesize(
        self,
        text: str,
        voice_id: str = "aura-asteria-en",
    ) -> bytes:
        url = f"{DG_TTS_REST_URL}?model={voice_id}"
        headers = {
            "Authorization": f"Token {self.api_key}",
            "Content-Type": "application/json",
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json={"text": text}, headers=headers) as resp:
                    if resp.status == 200:
                        return await resp.read()
                    error_text = await resp.text()
                    logger.error("Deepgram TTS REST failed: %s - %s", resp.status, error_text)
                    raise Exception(f"TTS failed with status {resp.status}")
        except Exception as e:
            logger.error("TTS synthesize failed: %s", e)
            raise

    # ──────────────────────────────────────────
    # WebSocket streaming TTS
    # Opens a WS, sends text, yields audio bytes.
    # Caller should await collect_sentence() to
    # get complete audio for a sentence.
    # ──────────────────────────────────────────
    async def synthesize_ws_stream(
        self,
        text: str,
        voice_id: str = "aura-asteria-en",
        encoding: str = "mp3",
        sample_rate: int = 16000,
    ) -> AsyncGenerator[bytes, None]:
        """Yields raw audio byte chunks via Deepgram TTS WebSocket."""
        params = urlencode({
            "model": voice_id,
            "encoding": encoding,
            "sample_rate": str(sample_rate)
        })
        url = f"{DG_TTS_WS_URL}?{params}"
        headers = {"Authorization": f"Token {self.api_key}"}

        try:
            async with websockets.connect(url, additional_headers=headers, ping_interval=None) as ws:
                # Send text
                await ws.send(json.dumps({"type": "Speak", "text": text}))
                await ws.send(json.dumps({"type": "Flush"}))

                async for msg in ws:
                    if isinstance(msg, bytes) and msg:
                        yield msg
                    elif isinstance(msg, str):
                        try:
                            data = json.loads(msg)
                            if data.get("type") == "Flushed":
                                # All audio for this request has been sent
                                await ws.send(json.dumps({"type": "Close"}))
                                break
                        except Exception:
                            pass
        except Exception as exc:
            logger.error("TTS WS error for text '%s...': %s", text[:40], exc)
            raise

    async def synthesize_sentence(
        self,
        text: str,
        voice_id: str = "aura-asteria-en",
    ) -> bytes:
        """Collect all audio bytes for a sentence via WS and return as one blob."""
        chunks: list[bytes] = []
        async for chunk in self.synthesize_ws_stream(text, voice_id):
            chunks.append(chunk)
        return b"".join(chunks)


class WarmTTSConnection:
    """
    Long-lived Deepgram TTS WebSocket for a session.
    Keeps the connection open; caller sends sentences one at a time.
    Supports barge-in via cancel().
    """

    def __init__(
        self,
        api_key: str,
        voice_id: str = "aura-asteria-en",
        encoding: str = "linear16",
        sample_rate: int = 16000
    ):
        self.api_key = api_key
        self.voice_id = voice_id
        self.encoding = encoding
        self.sample_rate = sample_rate
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._lock = asyncio.Lock()
        self._connect_task: Optional[asyncio.Task] = None

    async def connect(self) -> None:
        if self._ws and self._ws.state == websockets.State.OPEN:
            return

        async with self._lock:
            # Re-check inside lock
            if self._ws and self._ws.state == websockets.State.OPEN:
                return

            if self._connect_task is None or self._connect_task.done():
                async def _do_connect():
                    params = urlencode({
                        "model": self.voice_id,
                        "encoding": self.encoding,
                        "sample_rate": str(self.sample_rate)
                    })
                    url = f"{DG_TTS_WS_URL}?{params}"
                    headers = {"Authorization": f"Token {self.api_key}"}
                    self._ws = await websockets.connect(url, additional_headers=headers, ping_interval=None)
                    logger.info("Warm TTS WS connected (voice=%s, encoding=%s, rate=%d)", self.voice_id, self.encoding, self.sample_rate)

                self._connect_task = asyncio.create_task(_do_connect())

            await self._connect_task

    async def speak(self, text: str) -> AsyncGenerator[bytes, None]:
        """Send text and yield audio bytes until Flushed."""
        audio_chunks = []
        async with self._lock:
            if self._ws is None or self._ws.state != websockets.State.OPEN:
                await self.connect()

            ws = self._ws
            try:
                await ws.send(json.dumps({"type": "Speak", "text": text}))
                await ws.send(json.dumps({"type": "Flush"}))

                async for msg in ws:
                    if isinstance(msg, bytes) and msg:
                        audio_chunks.append(msg)
                    elif isinstance(msg, str):
                        try:
                            data = json.loads(msg)
                            if data.get("type") == "Flushed":
                                break
                        except Exception:
                            pass
            except Exception as exc:
                logger.error("WarmTTS speak error: %s", exc)
                self._ws = None
                self._connect_task = None
                raise

        for chunk in audio_chunks:
            yield chunk

    async def cancel(self) -> None:
        """Stop current synthesis (barge-in)."""
        if self._ws and self._ws.state == websockets.State.OPEN:
            try:
                await self._ws.send(json.dumps({"type": "Clear"}))
            except Exception:
                pass

    async def close(self) -> None:
        if self._ws and self._ws.state == websockets.State.OPEN:
            try:
                await self._ws.send(json.dumps({"type": "Close"}))
                await self._ws.close()
            except Exception:
                pass
        self._ws = None
        self._connect_task = None
