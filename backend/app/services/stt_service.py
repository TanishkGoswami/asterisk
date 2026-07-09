import asyncio
import json
import logging
from typing import AsyncGenerator
from urllib.parse import urlencode

import httpx
import websockets

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# Event types emitted by stream_live()
# ──────────────────────────────────────────────
EVT_INTERIM = "interim"
EVT_FINAL = "final"
EVT_SPEECH_FINAL = "speech_final"
EVT_UTTERANCE_END = "utterance_end"
EVT_SPEECH_STARTED = "speech_started"
EVT_ERROR = "error"


class STTService:
    def __init__(self, api_key: str):
        self.api_key = api_key

    # ──────────────────────────────────────────
    # Legacy REST (used by phone-webhook pipeline)
    # ──────────────────────────────────────────
    def transcribe_bytes(self, audio_bytes: bytes, language: str = "en-US") -> str:
        if not self.api_key:
            raise ValueError("Deepgram API key is missing")

        url = (
            f"https://api.deepgram.com/v1/listen"
            f"?model=nova-2&smart_format=true&language={language}"
        )
        headers = {
            "Authorization": f"Token {self.api_key}",
            "Content-Type": "audio/wav",
        }
        try:
            logger.info("REST STT: sending %d bytes to Deepgram", len(audio_bytes))
            response = httpx.post(url, headers=headers, content=audio_bytes, timeout=30.0)
            if response.status_code != 200:
                logger.error("Deepgram REST error: %s - %s", response.status_code, response.text)
                return ""
            data = response.json()
            channels = data.get("results", {}).get("channels", [])
            if not channels:
                return ""
            alternatives = channels[0].get("alternatives", [])
            if not alternatives:
                return ""
            transcript = alternatives[0].get("transcript", "")
            confidence = alternatives[0].get("confidence", 0)
            logger.info("REST STT transcript: '%s' (conf %.2f)", transcript, confidence)
            return transcript
        except Exception as e:
            logger.error("REST STT error: %s", e, exc_info=True)
            return ""

    # ──────────────────────────────────────────
    # Live WebSocket STT
    # Yields: (event_type: str, payload: dict)
    #   audio_queue: asyncio.Queue[bytes | None]
    #     — put bytes to forward audio, put None to close
    # ──────────────────────────────────────────
    async def stream_live(
        self,
        audio_queue: "asyncio.Queue[bytes | None]",
        language: str = "en-US",
        endpointing: int = 300,
        model: str = "nova-2",
        encoding: str = "linear16",
        sample_rate: str = "16000",
    ) -> AsyncGenerator[tuple[str, dict], None]:
        # Normalize language code for Deepgram STT (e.g. 'hi-IN' -> 'hi')
        if language and "-" in language:
            lang_code = language.split("-")[0].lower()
            if lang_code != "en":
                language = lang_code

        params = urlencode({
            "model": model,
            "language": language,
            "interim_results": "true",
            "vad_events": "true",
            "endpointing": str(endpointing),
            "smart_format": "true",
            "encoding": encoding,
            "sample_rate": sample_rate,
            "channels": "1",
        })
        url = f"wss://api.deepgram.com/v1/listen?{params}"
        headers = {"Authorization": f"Token {self.api_key}"}

        start_time = asyncio.get_event_loop().time()
        try:
            async with websockets.connect(url, additional_headers=headers, ping_interval=None) as dg_ws:
                conn_latency = int((asyncio.get_event_loop().time() - start_time) * 1000)
                from app.services.provider_health_service import log_provider_health_event
                asyncio.create_task(asyncio.to_thread(
                    log_provider_health_event,
                    provider="deepgram",
                    service_type="stt",
                    status="success",
                    latency_ms=conn_latency
                ))
                logger.info("Deepgram STT WS connected (endpointing=%dms)", endpointing)

                import time

                # Task: pump audio_queue → Deepgram
                async def _send_audio():
                    try:
                        while True:
                            chunk = await audio_queue.get()
                            if chunk is None:
                                logger.info(f"[STT_SEND_FLOW] Encountered EOF (None in queue) at timestamp={time.time()}")
                                # Signal Deepgram we're done sending
                                try:
                                    await dg_ws.send(json.dumps({"type": "CloseStream"}))
                                except Exception:
                                    pass
                                return
                            
                            logger.info(
                                f"[STT_SEND_FLOW] Dequeued chunk from audio_queue at timestamp={time.time()}, "
                                f"bytes={len(chunk)}, current_queue_size={audio_queue.qsize()}"
                            )
                            try:
                                await dg_ws.send(chunk)
                                logger.info(
                                    f"[STT_SEND_FLOW] Sent chunk to Deepgram at timestamp={time.time()}, "
                                    f"dg_ws_state={getattr(dg_ws, 'state', 'unknown')}"
                                )
                            except Exception as exc:
                                logger.warning(f"STT send error: {exc} at timestamp={time.time()}")
                                return
                    finally:
                        try:
                            await dg_ws.close()
                        except Exception:
                            pass

                # Task: keepalive
                async def _keepalive():
                    while True:
                        await asyncio.sleep(3)
                        try:
                            await dg_ws.send(json.dumps({"type": "KeepAlive"}))
                        except Exception:
                            return

                send_task = asyncio.create_task(_send_audio())
                keepalive_task = asyncio.create_task(_keepalive())

                try:
                    async for raw_msg in dg_ws:
                        logger.info(f"[STT_RECV_FLOW] Raw msg from Deepgram at timestamp={time.time()}: {raw_msg[:200]}")
                        if not isinstance(raw_msg, str):
                            continue
                        try:
                            msg = json.loads(raw_msg)
                        except Exception:
                            continue

                        msg_type = msg.get("type")

                        if msg_type == "Results":
                            channel = msg.get("channel", {})
                            alternatives = channel.get("alternatives", [])
                            transcript = alternatives[0].get("transcript", "") if alternatives else ""
                            confidence = alternatives[0].get("confidence", 0.0) if alternatives else 0.0
                            is_final: bool = msg.get("is_final", False)
                            speech_final: bool = msg.get("speech_final", False)

                            if not transcript:
                                continue

                            payload = {
                                "transcript": transcript,
                                "confidence": confidence,
                                "is_final": is_final,
                                "speech_final": speech_final,
                            }

                            if speech_final:
                                logger.info("STT speech_final: '%s'", transcript)
                                yield EVT_SPEECH_FINAL, payload
                            elif is_final:
                                yield EVT_FINAL, payload
                            else:
                                yield EVT_INTERIM, payload

                        elif msg_type == "UtteranceEnd":
                            logger.info("STT UtteranceEnd")
                            yield EVT_UTTERANCE_END, {"last_word_end": msg.get("last_word_end")}

                        elif msg_type == "SpeechStarted":
                            yield EVT_SPEECH_STARTED, {"timestamp": msg.get("timestamp")}

                        elif msg_type == "Error":
                            logger.error("Deepgram STT error: %s", msg)
                            yield EVT_ERROR, {"message": str(msg)}

                finally:
                    send_task.cancel()
                    keepalive_task.cancel()

        except Exception as exc:
            conn_latency = int((asyncio.get_event_loop().time() - start_time) * 1000)
            from app.services.provider_health_service import log_provider_health_event
            asyncio.create_task(asyncio.to_thread(
                log_provider_health_event,
                provider="deepgram",
                service_type="stt",
                status="failure",
                latency_ms=conn_latency,
                error_code="WS_CONN_ERROR",
                error_message=str(exc)
            ))
            logger.error("STT WS connection error: %s", exc, exc_info=True)
            yield EVT_ERROR, {"message": str(exc)}
