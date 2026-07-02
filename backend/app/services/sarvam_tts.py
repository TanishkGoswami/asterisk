import asyncio
import base64
import logging
import audioop
import json
import re
from typing import AsyncGenerator, Optional
import aiohttp
import websockets

from app.core.config import settings
from app.services.tts_service import TTSService

logger = logging.getLogger(__name__)

def prepare_for_tts(text: str) -> str:
    """
    Preprocess text before sending to Sarvam TTS to improve naturalness:
    - Replace all question marks (?) and exclamation marks (!) with periods (.)
    - Collapse repeated punctuation (e.g. consecutive periods or commas)
    - Normalize whitespace
    - Remove duplicate punctuation sequences
    """
    if not text:
        return text
    
    # 1. Replace all question marks (?) and exclamation marks (!) with periods (.)
    processed = text.replace('?', '.').replace('!', '.')
    
    # 2. Collapse repeated/duplicate periods (including spaces between them) to a single period
    processed = re.sub(r'\.[\s\.]*\.', '.', processed)
    
    # 3. Collapse repeated/duplicate commas
    processed = re.sub(r',[\s,]*,', ',', processed)
    
    # 4. Normalize whitespace: collapse multiple spaces/tabs/newlines to a single space
    processed = re.sub(r'\s+', ' ', processed)
    
    return processed.strip()

SARVAM_REST_URL = "https://api.sarvam.ai/text-to-speech"
SARVAM_STREAM_URL = "https://api.sarvam.ai/text-to-speech/stream"

class SarvamTTSService:
    def __init__(self, api_key: str):
        self.api_key = api_key
        # We instantiate a Deepgram fallback TTS service
        self.fallback_service = TTSService(settings.deepgram_api_key or "")
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    async def convert_text_to_speech(
        self,
        text: str,
        speaker: str = "shubh",
        language: str = "hi-IN",
        output_audio_codec: str = "mp3",
        pace: float = 1.0
    ) -> bytes:
        """
        Synthesize text to speech using Sarvam REST API.
        If output_audio_codec is 'mulaw', we request 'linear16' from Sarvam,
        resample from 24kHz to 8kHz, and convert to u-law.
        If output_audio_codec is 'pcm', we request 'linear16' from Sarvam
        and resample from 24kHz to 16kHz.
        """
        text = prepare_for_tts(text)
        if len(text) > 400:
            import re
            logger.info("Text is too long (%d chars) for Sarvam TTS. Splitting into smaller chunks.", len(text))
            # Split by common sentence boundaries
            sentences = re.split(r'(?<=[.!?|।\n])\s+', text)
            chunks = []
            current_chunk = ""
            for sentence in sentences:
                if len(current_chunk) + len(sentence) + 1 <= 400:
                    if current_chunk:
                        current_chunk += " " + sentence
                    else:
                        current_chunk = sentence
                else:
                    if current_chunk:
                        chunks.append(current_chunk)
                    # If a single sentence is itself > 400 chars, split it by slicing
                    if len(sentence) > 400:
                        sub_sentences = [sentence[i:i+400] for i in range(0, len(sentence), 400)]
                        chunks.extend(sub_sentences[:-1])
                        current_chunk = sub_sentences[-1]
                    else:
                        current_chunk = sentence
            if current_chunk:
                chunks.append(current_chunk)
            
            # Synthesize all chunks and concatenate
            audio_segments = []
            for chunk in chunks:
                if chunk.strip():
                    segment = await self.convert_text_to_speech(
                        text=chunk.strip(),
                        speaker=speaker,
                        language=language,
                        output_audio_codec=output_audio_codec,
                        pace=pace
                    )
                    audio_segments.append(segment)
            return b"".join(audio_segments)

        if not self.api_key or self.api_key == "your_sarvam_api_key":
            logger.warning("Sarvam API key is not configured. Falling back to Deepgram.")
            return await self._fallback_synthesize(text)

        # For mulaw and pcm, request linear16 from Sarvam
        req_codec = "linear16" if output_audio_codec in ("mulaw", "pcm") else output_audio_codec

        headers = {
            "api-subscription-key": self.api_key,
            "Content-Type": "application/json"
        }
        payload = {
            "inputs": [text],
            "target_language_code": language,
            "speaker": speaker,
            "model": "bulbul:v3",
            "output_audio_codec": req_codec,
            "pace": pace
        }

        if output_audio_codec == "pcm":
            payload["speech_sample_rate"] = 16000
        elif output_audio_codec == "mulaw":
            payload["speech_sample_rate"] = 8000

        try:
            session = await self._get_session()
            timeout = aiohttp.ClientTimeout(total=30)
            async with session.post(SARVAM_REST_URL, json=payload, headers=headers, timeout=timeout) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    raise RuntimeError(f"Sarvam API error: Status {resp.status} - {error_text}")
                
                data = await resp.json()
                audios = data.get("audios", [])
                if not audios:
                    raise RuntimeError("Sarvam API returned empty audios array")
                
                audio_bytes = base64.b64decode(audios[0])

                if req_codec == "linear16":
                    # Strip WAV header if present to extract raw PCM bytes
                    if audio_bytes.startswith(b"RIFF") and b"WAVE" in audio_bytes[:16]:
                        data_idx = audio_bytes.find(b"data")
                        if data_idx != -1:
                            audio_bytes = audio_bytes[data_idx + 8:]
                        else:
                            audio_bytes = audio_bytes[44:]

                if output_audio_codec == "mulaw":
                    # Convert 8kHz 16-bit mono PCM to 8-bit mulaw
                    try:
                        mulaw_data = audioop.lin2ulaw(audio_bytes, 2)
                        return mulaw_data
                    except Exception as err:
                        logger.error("Failed to convert Sarvam PCM to 8kHz mulaw: %s", err)
                        raise
                elif output_audio_codec == "pcm":
                    # Already 16kHz PCM mono, return as is
                    return audio_bytes

                return audio_bytes

        except Exception as exc:
            logger.error("Sarvam TTS synthesis failed: %s. Falling back to Deepgram.", exc)
            return await self._fallback_synthesize(text)

    async def stream_text_to_speech(
        self,
        text: str,
        speaker: str = "shubh",
        language: str = "hi-IN",
        output_audio_codec: str = "mp3",
        pace: float = 1.0
    ) -> AsyncGenerator[bytes, None]:
        """
        Stream text to speech using Sarvam REST API by fully buffering the audio.
        The Sarvam /stream endpoint is unreliable and hangs, so we use the REST endpoint.
        """
        if not self.api_key or self.api_key == "your_sarvam_api_key":
            logger.warning("Sarvam API key is not configured. Falling back to Deepgram stream.")
            async for chunk in self._fallback_stream(text, codec=output_audio_codec):
                yield chunk
            return

        try:
            # Generate the full audio buffer via the REST API
            audio_bytes = await self.convert_text_to_speech(
                text=text,
                speaker=speaker,
                language=language,
                output_audio_codec=output_audio_codec,
                pace=pace
            )
            
            # Yield it in small chunks to simulate streaming
            chunk_size = 4096
            for i in range(0, len(audio_bytes), chunk_size):
                yield audio_bytes[i:i + chunk_size]

        except Exception as exc:
            logger.error("Sarvam TTS stream via REST failed: %s. Falling back to Deepgram stream.", exc)
            async for chunk in self._fallback_stream(text, codec=output_audio_codec):
                yield chunk

    async def health_check(self) -> bool:
        """Verify API key and endpoint connectivity with a tiny request."""
        if not self.api_key or self.api_key == "your_sarvam_api_key":
            return False
        try:
            # Try to synthesize a period character
            await self.convert_text_to_speech(".", speaker="shubh", language="hi-IN")
            return True
        except Exception as e:
            logger.warning("Sarvam TTS Health Check failed: %s", e)
            return False

    async def _fallback_synthesize(self, text: str) -> bytes:
        """Fallback helper to synthesize using Deepgram."""
        logger.info("Using Deepgram fallback for synthesis.")
        # Map or use default female voice for fallback
        return await self.fallback_service.synthesize(text, voice_id="aura-asteria-en")

    async def _fallback_stream(self, text: str, codec: str = "mp3") -> AsyncGenerator[bytes, None]:
        """Fallback helper to stream using Deepgram."""
        logger.info("Using Deepgram fallback for streaming.")
        enc = "mulaw" if codec == "mulaw" else ("linear16" if codec == "pcm" else codec)
        sr = 8000 if codec == "mulaw" else 16000
        async for chunk in self.fallback_service.synthesize_ws_stream(text, voice_id="aura-asteria-en", encoding=enc, sample_rate=sr):
            yield chunk


class WarmSarvamConnection:
    """
    Long-lived Sarvam TTS WebSocket connection for a session.
    Keeps the connection open; caller sends sentences one at a time.
    """
    def __init__(
        self,
        api_key: str,
        speaker: str = "shubh",
        language: str = "hi-IN",
        model: str = "bulbul:v3",
        output_audio_codec: str = "pcm",
        pace: float = 1.0
    ):
        self.api_key = api_key
        self.speaker = speaker
        self.language = language
        self.model = model
        self.output_audio_codec = output_audio_codec
        self.pace = pace
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
                    url = f"wss://api.sarvam.ai/text-to-speech/ws?model={self.model}&send_completion_event=true"
                    headers = {"api-subscription-key": self.api_key}
                    self._ws = await websockets.connect(url, additional_headers=headers, ping_interval=None)
                    
                    # Map output codec names
                    codec = self.output_audio_codec
                    if codec == "pcm":
                        codec = "linear16"

                    # Send configuration message first
                    config_msg = {
                        "type": "config",
                        "data": {
                            "target_language_code": self.language,
                            "speaker": self.speaker,
                            "model": self.model,
                            "output_audio_codec": codec,
                            "pace": self.pace
                        }
                    }
                    if codec == "linear16":
                        config_msg["data"]["speech_sample_rate"] = 16000
                    elif codec == "mulaw":
                        config_msg["data"]["speech_sample_rate"] = 8000

                    await self._ws.send(json.dumps(config_msg))
                    logger.info("Warm Sarvam TTS WS connected (speaker=%s, lang=%s, codec=%s)", self.speaker, self.language, codec)

                self._connect_task = asyncio.create_task(_do_connect())

            await self._connect_task

    async def speak(self, text: str) -> AsyncGenerator[bytes, None]:
        """Send text and yield audio bytes until flushed."""
        text = prepare_for_tts(text)
        audio_chunks = []
        async with self._lock:
            if self._ws is None or self._ws.state != websockets.State.OPEN:
                await self.connect()

            ws = self._ws
            try:
                # Send text payload
                text_msg = {
                    "type": "text",
                    "data": {
                        "text": text
                    }
                }
                await ws.send(json.dumps(text_msg))
                
                # Send flush payload
                flush_msg = {
                    "type": "flush"
                }
                await ws.send(json.dumps(flush_msg))

                # Receive all audio chunks
                async for raw_msg in ws:
                    msg = json.loads(raw_msg)
                    msg_type = msg.get("type")
                    if msg_type == "audio":
                        audio_b64 = msg.get("data", {}).get("audio", "")
                        if audio_b64:
                            audio_chunks.append(base64.b64decode(audio_b64))
                    elif msg_type == "flushed":
                        break
                    elif msg_type == "event":
                        event_type = msg.get("data", {}).get("event_type")
                        if event_type == "final":
                            break
                    elif msg_type == "error":
                        error_msg = msg.get("data", {}).get("message", "Unknown Sarvam WS error")
                        raise RuntimeError(f"Sarvam WS error: {error_msg}")
            except BaseException as exc:
                logger.error("WarmSarvam speak error or cancellation: %s", exc)
                if self._ws:
                    try:
                        await self._ws.close()
                    except Exception:
                        pass
                self._ws = None
                self._connect_task = None
                raise

        for chunk in audio_chunks:
            yield chunk

    async def close(self) -> None:
        if self._ws and self._ws.state == websockets.State.OPEN:
            try:
                await self._ws.close()
            except Exception:
                pass
        self._ws = None
        self._connect_task = None
