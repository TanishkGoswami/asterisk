"""
Minimum-latency WebSocket voice pipeline.

Protocol (Frontend ↔ Backend):
  Frontend → Backend:
    binary frames  : raw PCM audio (16-bit signed, 16 kHz, mono)
    JSON {"type": "config", "voice_id": "...", "system_prompt": "...",
          "model": "...", "knowledge_base": "...", "language": "en-US"}
    JSON {"type": "barge_in"}
    JSON {"type": "end_session"}

  Backend → Frontend:
    binary frames  : MP3 audio bytes (one complete sentence per frame)
    JSON {"type": "ready"}
    JSON {"type": "transcript", "text": "...", "is_final": bool, "speech_final": bool}
    JSON {"type": "llm_text", "text": "..."}
    JSON {"type": "stop_audio"}
    JSON {"type": "turn_end"}
    JSON {"type": "latency", "stt_eot_ms": X, "llm_first_token_ms": X,
          "tts_first_byte_ms": X, "total_perceived_ms": X}
    JSON {"type": "error", "message": "..."}
"""

import asyncio
import json
import logging
import re
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.config import settings
from app.services.latency_tracker import (
    LatencyTracker,
    USER_SPEECH_STARTED,
    USER_SPEECH_ENDED,
    DEEPGRAM_FIRST_INTERIM,
    DEEPGRAM_FINAL,
    LLM_REQUEST_STARTED,
    LLM_FIRST_TOKEN,
    FIRST_TTS_CHUNK_SENT,
    SARVAM_FIRST_AUDIO_BYTE,
    AUDIO_PLAYBACK_STARTED,
    AUDIO_PLAYBACK_COMPLETED,
    AUDIO_RECEIVED,
)
from app.services.llm_service import LLMService
from app.services.stt_service import (
    STTService,
    EVT_INTERIM,
    EVT_FINAL,
    EVT_SPEECH_FINAL,
    EVT_UTTERANCE_END,
    EVT_SPEECH_STARTED,
    EVT_ERROR,
)
from app.services.tts_service import WarmTTSConnection
from app.services.sarvam_tts import SarvamTTSService, WarmSarvamConnection
from app.services.tts_router import route_tts
from app.voice_config import voice_cfg

logger = logging.getLogger(__name__)

# Add a runtime debug file handler to log everything in ws_runtime.log
try:
    import os
    runtime_log_path = os.path.abspath(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "ws_runtime.log"))
    fh = logging.FileHandler(runtime_log_path, mode="a", encoding="utf-8")
    fh.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    fh.setFormatter(formatter)
    # Configure handlers for our services too
    logging.getLogger("app").addHandler(fh)
    logging.getLogger("app").setLevel(logging.INFO)
    logger.info(f"Initialized runtime debug file logging at {runtime_log_path}")
except Exception as e:
    print(f"Failed to setup debug file logging: {e}")

router = APIRouter()

_SARVAM_SPEAKER_META: dict[str, str] = {
    "shubh":  "male",
    "meera":  "female",
    "shreya": "female",
    "manan": "male",
    "ishita": "female",
    "arjun":  "male",
    "aayan":  "male",
    "aditya": "male",
    "advait": "male",
    "amit":   "male",
    "anand":  "male",
    "ashutosh": "male",
    "dev":    "male",
    "gokul":  "male",
    "kabir":  "male",
    "kavitha": "female",
    "kavya":  "female",
    "mani":   "male",
    "mohit":  "male",
    "neha":   "female",
    "pooja":  "female",
    "priya":  "female",
    "rahul":  "male",
    "ratan":  "male",
    "rehan":  "male",
    "ritu":   "female",
    "rohan":  "male",
    "roopa":  "female",
    "rupali": "female",
    "shruti": "female",
    "simran": "female",
    "soham":  "male",
    "suhani": "female",
    "sumit":  "male",
    "sunny":  "male",
    "tanya":  "female",
    "tarun":  "male",
    "varun":  "male",
    "vijay":  "male",
}

def _map_sarvam_speaker(voice_id: str, voice_gender: str | None = None) -> str:
    """Map a voice_id string to a Sarvam speaker name."""
    voice_lower = voice_id.lower() if voice_id else ""
    # Map unsupported speakers to valid alternatives
    if "meera" in voice_lower:
        return "shreya"
    if "arjun" in voice_lower:
        return "shubh"

    # 1. Direct match
    for spk in _SARVAM_SPEAKER_META:
        if spk in voice_lower:
            return spk
    # 2. Explicit gender hint
    if voice_gender:
        g = voice_gender.lower()
        for spk, gender in _SARVAM_SPEAKER_META.items():
            if gender == g:
                if spk == "meera":
                    return "shreya"
                if spk == "arjun":
                    return "shubh"
                return spk
    # 3. Deepgram female voice name heuristics
    if any(g in voice_lower for g in ["asteria", "luna", "stella", "athena", "hera", "thalia", "amalthea", "female"]):
        return "shreya"
    # 4. Default male
    return "shubh"



SENTENCE_END = re.compile(r'(?<=[.!?])\s+|(?<=[.!?])$')


def _split_first_sentence(text: str) -> tuple[str, str]:
    """Return (first_sentence, remainder)."""
    parts = SENTENCE_END.split(text, maxsplit=1)
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()
    return text.strip(), ""


def _word_count(text: str) -> int:
    return len(text.split())


def _ends_sentence(text: str) -> bool:
    return bool(text.rstrip()) and text.rstrip()[-1] in ".!?"


def _resolve_deepgram_voice(voice_id: str | None, voice_gender: str | None = None) -> str:
    if not voice_id or not voice_id.lower().startswith("aura-"):
        from app.utils.post_processor import detect_voice_gender
        gender = voice_gender.lower() if voice_gender else detect_voice_gender(voice_id)
        if gender == "male":
            return "aura-arcas-en"
        return "aura-asteria-en"
    return voice_id


def _get_male_persona_block() -> str:
    return """--- Voice Agent Persona ---
You are a male Indian voice assistant.
Speak in natural Hinglish, not pure Hindi.
Your tone should feel like a polite male Indian support executive.
Use Hindi grammar with common English words.

Always use male-gendered first-person phrases:
“sakta hoon”, “gaya”, “leta hoon”, “deta hoon”.
Never use female-gendered phrases:
“sakti hoon”, “gayi”, “leti hoon”, “deti hoon”.

Examples:
User: Mujhe plan ke baare me batao
Assistant: Ji, main aapko plan details bata deta hoon. Aap monthly plan dekhna chahenge ya yearly?

User: Ye kaise kaam karta hai?
Assistant: Ji, main samjha deta hoon. Ye system aapke customer ki call receive karta hai, unki baat samajhta hai, aur phir proper response deta hai.

User: Kya aap booking kar sakte ho?
Assistant: Haan ji, main booking kar sakta hoon. Aap mujhe date aur time bata dijiye.

User: Samjhe?
Assistant: Haan ji, main samajh gaya.

Response rules:
* Keep replies under 2–3 sentences.
* For calls, avoid long paragraphs.
* Ask one question at a time.
* Use Hinglish spelling in Roman Hindi if the user speaks Roman Hindi.
* Use Devanagari only if the user speaks Devanagari Hindi.
* Do not sound robotic.
* Do not overuse “kripya”, “avashya”, “sahayata”, “pratiksha”.
* Prefer “please”, “sure”, “help”, “check”, “details”, “booking”, “call”, “plan”.
"""


def _get_female_persona_block() -> str:
    return """--- Voice Agent Persona ---
You are a female Indian voice assistant.
Speak in natural Hinglish, not pure Hindi.
Your tone should feel like a polite female Indian support executive.
Use Hindi grammar with common English words.

Always use female-gendered first-person phrases:
“sakti hoon”, “gayi”, “leti hoon”, “deti hoon”.
Never use male-gendered phrases:
“sakta hoon”, “gaya”, “leta hoon”, “deta hoon”.

Examples:
User: Mujhe plan ke baare me batao
Assistant: Ji, main aapko plan details bata deti hoon. Aap monthly plan dekhna chahenge ya yearly?

User: Ye kaise kaam karta hai?
Assistant: Ji, main samjha deti hoon. Ye system aapke customer ki call receive karta hai, unki baat samajhta hai, aur phir proper response deta hai.

User: Kya aap booking kar sakte ho?
Assistant: Haan ji, main booking kar sakti hoon. Aap mujhe date aur time bata dijiye.

User: Samjhe?
Assistant: Haan ji, main samajh gayi.

Response rules:
* Keep replies under 2–3 sentences.
* For calls, avoid long paragraphs.
* Ask one question at a time.
* Use Hinglish spelling in Roman Hindi if the user speaks Roman Hindi.
* Use Devanagari only if the user speaks Devanagari Hindi.
* Do not sound robotic.
* Do not overuse “kripya”, “avashya”, “sahayata”, “pratiksha”.
* Prefer “please”, “sure”, “help”, “check”, “details”, “booking”, “call”, “plan”.
"""


# ─────────────────────────────────────────────────────────────
# Session state
# ─────────────────────────────────────────────────────────────
import os

# ─────────────────────────────────────────────────────────────
# Session state
# ─────────────────────────────────────────────────────────────
class VoiceSession:
    def __init__(self, ws: WebSocket):
        self.ws = ws
        self.config: dict = {}
        self.messages: list[dict] = []        # conversation history
        self.latest_transcript: str = ""
        self.audio_queue: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=200)
        self.llm_tts_task: Optional[asyncio.Task] = None
        self.tts_tasks: list[asyncio.Task] = []
        self.tts_conn: Optional[WarmTTSConnection] = None
        self.sarvam_tts_conn: Optional[WarmSarvamConnection] = None
        self.sarvam_tts = SarvamTTSService(settings.sarvam_api_key or "")
        self.barge_in_event = asyncio.Event()
        self.latency = LatencyTracker()
        self._state = "idle"   # idle | listening | processing | speaking
        self.speaking_started_at: float = 0.0
        self.is_twilio = False
        self.stream_sid = ""
        self.call_db_id: Optional[str] = None
        self.message_sequence: int = 0

    def is_speaking(self) -> bool:
        return self._state == "speaking"

    def set_state(self, state: str):
        import time
        logger.info(f"[TELEMETRY_STATE] transition: '{self._state}' -> '{state}' at timestamp={time.time()}")
        self._state = state

    async def send_json(self, data: dict):
        """Send JSON (control message) if connected."""
        if self.is_twilio and data.get("event") not in ("media", "mark", "clear"):
            # Do not send custom frontend events to Twilio, it will crash the stream
            return
            
        try:
            # Check FastAPI WebSocket state
            await self.ws.send_json(data)
        except Exception as e:
            logger.error(f"Error sending JSON: {e}")

    async def send_bytes(self, data: bytes):
        try:
            await self.ws.send_bytes(data)
        except Exception:
            pass

    async def send_audio(self, audio_data: bytes):
        """Send audio out either as binary (browser) or JSON base64 (Twilio)."""
        if self.is_twilio and self.stream_sid:
            import base64
            b64_audio = base64.b64encode(audio_data).decode("utf-8")
            await self.send_json({
                "event": "media",
                "streamSid": self.stream_sid,
                "media": {
                    "payload": b64_audio
                }
            })
        else:
            await self.send_bytes(audio_data)

    async def cancel_llm_tts(self):
        """Cancel any ongoing LLM or TTS tasks."""
        logger.info("[CANCEL_PREVIOUS_RESPONSE] Cancelling previous LLM/TTS response tasks.")
        
        if self.llm_tts_task and not self.llm_tts_task.done():
            self.llm_tts_task.cancel()
            try:
                await self.llm_tts_task
            except asyncio.CancelledError:
                pass
        
        # Cancel all background parallel TTS tasks
        for task in self.tts_tasks:
            if not task.done():
                task.cancel()
        self.tts_tasks = []
        
        if self.tts_conn:
            await self.tts_conn.cancel()
        # Do not close the sarvam connection on turn cancel/barge-in so it stays warm.
        # If an active synthesis is running, the cancellation of its task will trigger
        # exception handling inside speak() which automatically cleans up.
            
        if self.is_twilio and self.stream_sid:
            await self.send_json({
                "event": "clear",
                "streamSid": self.stream_sid
            })
            
        logger.info("[AUDIO_QUEUE_CLEARED] Backend TTS queues cancelled and cleared.")
        self._state = "idle"
        self.speaking_started_at = 0.0

    def _build_system_prompt(self) -> str:
        base = (self.config.get("agent_system_prompt") or self.config.get("system_prompt") or "You are a helpful voice assistant.").strip()
        kb = (self.config.get("knowledge_base") or "").strip()
        
        # Get resolved voice gender and language settings
        voice_id = self.config.get("voice_id")
        voice_gender = self.config.get("voice_gender")
        from app.utils.post_processor import detect_voice_gender
        gender = voice_gender.lower() if voice_gender else detect_voice_gender(voice_id)
        
        # Determine language (Hinglish/English vs pure Hindi)
        language = (self.config.get("language") or "en-US").lower()
        is_hindi = language.startswith("hi") or (self.config.get("tts_provider") == "sarvam")

        # Swap the Voice Agent Persona block dynamically to match the current gender
        if "--- Voice Agent Persona ---" in base:
            parts = base.split("--- Voice Agent Persona ---")
            header = parts[0].strip()
            persona_block = _get_male_persona_block() if gender == "male" else _get_female_persona_block()
            base = f"{header}\n\n{persona_block}"
        else:
            # Fallback override if the block is not structured
            if is_hindi:
                if gender == "male":
                    base += "\n\nOVERRIDE: आप एक पुरुष (male) भारतीय वॉयस असिस्टेंट हैं। बातचीत में पुल्लिंग हिंदी व्याकरण नियमों का उपयोग करें, जैसे: 'सकता हूँ', 'गया', 'लेता हूँ', 'देता हूँ'। स्त्रीलिंग शब्द या क्रियाओं का उपयोग न करें।"
                else:
                    base += "\n\nOVERRIDE: आप एक महिला (female) भारतीय वॉयस असिस्टेंट हैं। बातचीत में स्त्रीलिंग हिंदी व्याकरण नियमों का उपयोग करें, जैसे: 'सकती हूँ', 'गई', 'लेती हूँ', 'देती हूँ'। पुल्लिंग शब्द या क्रियाओं का उपयोग न करें।"
            else:
                if gender == "male":
                    base += "\n\nOVERRIDE: You are a male Indian voice assistant. Use male Hinglish grammar rules: 'sakta hoon', 'gaya', 'leta hoon', 'deta hoon'. Do NOT use female phrases."
                else:
                    base += "\n\nOVERRIDE: You are a female Indian voice assistant. Use female Hinglish grammar rules: 'sakti hoon', 'gayi', 'leti hoon', 'deti hoon'. Do NOT use male phrases."

        # Strict prompt instructions based on the selected language
        if is_hindi:
            voice_prefix = (
                "You are a real-time voice assistant. You MUST answer in short, natural Hindi (Devanagari script). "
                "Do NOT use Roman Hinglish. Speak and reply using clean, conversational Hindi. "
                "Maximum response length: 1–2 sentences. Avoid long explanations. "
                "Keep replies brief, direct, and conversational."
            )
        else:
            voice_prefix = (
                "You are a real-time voice assistant. You MUST answer in short Hinglish. "
                "Maximum response length: 1–2 sentences. Avoid long explanations. "
                "Use natural spoken language. Never generate paragraphs for voice calls. "
                "Keep replies brief, direct, and conversational."
            )

        full = f"{voice_prefix}\n\n{base}"
        if kb:
            full += f"\n\nKnowledge base:\n{kb}"
        return full

    async def trigger_initial_greeting(self):
        """Generate and play the first greeting to the caller without waiting for user speech."""
        logger.info("[GREETING_TRIGGERED] Triggering initial greeting asynchronously")
        # Start the LLM pipeline for greeting
        self.llm_tts_task = asyncio.create_task(
            self.run_llm_tts_pipeline("", is_greeting=True)
        )

    async def run_llm_tts_pipeline(self, transcript: str, is_greeting: bool = False):
        """STT → LLM stream → sentence buffering → TTS WS → audio to frontend."""
        self.set_state("processing")
        tracker = self.latency

        # Pre-calculate sequence numbers for this turn to prevent race conditions
        if not is_greeting and transcript.strip():
            user_seq = self.message_sequence + 1
            assistant_seq = self.message_sequence + 2
            self.message_sequence = assistant_seq
        else:
            user_seq = None
            assistant_seq = self.message_sequence + 1
            self.message_sequence = assistant_seq

        llm = LLMService(
            openai_key=settings.openai_api_key,
        )
        model = self.config.get("model") or voice_cfg.OPENAI_VOICE_MODEL
        voice_id = self.config.get("voice_id") or "aura-asteria-en"
        tts_provider = self.config.get("tts_provider") or "deepgram"
        language = self.config.get("language") or "en-US"

        # Resolve TTS provider early to pre-warm the connection in the background
        early_provider = route_tts("", tts_provider, language, voice_id)
        if early_provider == "sarvam":
            speaker = _map_sarvam_speaker(voice_id, self.config.get("voice_gender"))
            codec = "mulaw" if self.is_twilio else "pcm"
            speed = float(self.config.get("voice_speed") or 0.95)
            speed = max(0.5, min(2.0, speed))
            if (self.sarvam_tts_conn is None 
                or self.sarvam_tts_conn.speaker != speaker 
                or self.sarvam_tts_conn.output_audio_codec != codec
                or getattr(self.sarvam_tts_conn, "pace", 1.0) != speed):
                if self.sarvam_tts_conn:
                    asyncio.create_task(self.sarvam_tts_conn.close())
                self.sarvam_tts_conn = WarmSarvamConnection(
                    api_key=settings.sarvam_api_key or "",
                    speaker=speaker,
                    language="hi-IN",
                    output_audio_codec=codec,
                    pace=speed
                )
            logger.info("[PRE_WARM] Pre-warming Sarvam WS connection in the background...")
            asyncio.create_task(self.sarvam_tts_conn.connect())
        elif early_provider == "deepgram":
            dg_voice = _resolve_deepgram_voice(voice_id, self.config.get("voice_gender"))
            enc = "mulaw" if self.is_twilio else "linear16"
            sr = 8000 if self.is_twilio else 16000
            if (self.tts_conn is None 
                or self.tts_conn.voice_id != dg_voice 
                or self.tts_conn.encoding != enc 
                or self.tts_conn.sample_rate != sr):
                if self.tts_conn:
                    asyncio.create_task(self.tts_conn.close())
                self.tts_conn = WarmTTSConnection(
                    api_key=settings.deepgram_api_key or "",
                    voice_id=dg_voice,
                    encoding=enc,
                    sample_rate=sr
                )
            logger.info("[PRE_WARM] Pre-warming Deepgram WS connection in the background...")
            asyncio.create_task(self.tts_conn.connect())

        # Record user message in DB
        if not is_greeting and transcript.strip():
            self.messages.append({"role": "user", "content": transcript})
            if self.call_db_id and user_seq:
                try:
                    from datetime import datetime, timezone
                    from app.db.client import get_supabase_client
                    def _insert_user_msg(seq: int):
                        db = get_supabase_client()
                        db.table("call_messages").insert({
                            "call_id": self.call_db_id,
                            "role": "user",
                            "content": transcript,
                            "sequence_number": seq,
                            "started_at": datetime.now(timezone.utc).isoformat(),
                        }).execute()
                        logger.info(f"[DB_LOG] User message sequence {seq} inserted: '{transcript}'")
                    
                    asyncio.create_task(asyncio.to_thread(_insert_user_msg, user_seq))
                except Exception as e:
                    logger.error(f"[DB_LOG_ERROR] Failed to start user message DB insert: {e}")

        # Build prompt/history for LLM
        if is_greeting:
            prompt_instruction = "Generate a short, friendly, conversational welcome greeting for the caller to start the call."
            if language.lower().startswith("hi"):
                prompt_instruction += " Speak in Roman Hinglish (mix of Hindi/English)."
            else:
                prompt_instruction += " Speak in English."
            
            compressed_history = [{"role": "user", "content": prompt_instruction}]
        else:
            compressed_history = self.messages[-10:]

        tracker.mark(LLM_REQUEST_STARTED)

        # Smart Token Chunking Buffer State
        token_buffer = ""
        first_token_marked = False
        full_response = ""

        # Map to hold audio queues for each parallel TTS chunk index
        chunk_queues: dict[int, asyncio.Queue[bytes | None]] = {}
        stream_finished_event = asyncio.Event()
        task_index = 0

        # Sequence ordering playback worker
        async def playback_worker():
            current_index = 0
            audio_playback_started_marked = False

            while True:
                # Wait until the queue for the current index is registered
                while current_index not in chunk_queues and not stream_finished_event.is_set():
                    await asyncio.sleep(0.01)

                if current_index not in chunk_queues and stream_finished_event.is_set():
                    # All queues are finished and processed
                    break

                queue = chunk_queues[current_index]
                while True:
                    audio_chunk = await queue.get()
                    if audio_chunk is None:
                        break
                    
                    if not self.barge_in_event.is_set():
                        if not audio_playback_started_marked:
                            import time
                            logger.info(f"[TELEMETRY_TTS] TTS playback starting at timestamp={time.time()}")
                            tracker.mark(AUDIO_PLAYBACK_STARTED)
                            audio_playback_started_marked = True
                            self.set_state("speaking")
                            self.speaking_started_at = time.time()
                        await self.send_audio(audio_chunk)

                current_index += 1

            import time
            if not self.barge_in_event.is_set():
                logger.info(f"[TELEMETRY_TTS] TTS playback ended cleanly at timestamp={time.time()}")
                tracker.mark(AUDIO_PLAYBACK_COMPLETED)
                if self.is_twilio and self.stream_sid:
                    await self.send_json({"event": "mark", "streamSid": self.stream_sid, "mark": {"name": "turn_end"}})
                else:
                    await self.send_json({"type": "turn_end"})
            else:
                logger.info(f"[TELEMETRY_TTS] TTS playback interrupted (barge-in active) at timestamp={time.time()}")
                
                lat_summary = tracker.summary()
                await self.send_json({"type": "latency", **lat_summary})

                if self.call_db_id and assistant_seq:
                    try:
                        from app.db.client import get_supabase_client
                        def _update_call_metadata(call_id: str, seq: int, summary: dict):
                            db = get_supabase_client()
                            res = db.table("calls").select("metadata").eq("id", call_id).execute()
                            if res.data:
                                metadata = res.data[0].get("metadata") or {}
                                if "latency_by_sequence" not in metadata:
                                    metadata["latency_by_sequence"] = {}
                                metadata["latency_by_sequence"][str(seq)] = summary
                                db.table("calls").update({"metadata": metadata}).eq("id", call_id).execute()
                                logger.info(f"[DB_LOG] Saved latency metrics for sequence {seq} in calls table metadata")
                        
                        asyncio.create_task(asyncio.to_thread(_update_call_metadata, self.call_db_id, assistant_seq, lat_summary))
                    except Exception as e:
                        logger.error(f"[DB_LOG_ERROR] Failed to update call metadata with latency: {e}")

        # Pre-warm cached voice phrase helper
        voice_gender = self.config.get("voice_gender")
        from app.utils.post_processor import detect_voice_gender
        gender = voice_gender.lower() if voice_gender else detect_voice_gender(voice_id)

        def check_voice_cache(text: str) -> Optional[bytes]:
            normalized = text.lower().strip().translate(str.maketrans("", "", '.,!?।""\'\''))
            cache_map = {
                "ji": "filler_ji_shubh.pcm" if gender == "male" else "filler_ji_shreya.pcm",
                "haan": "filler_haan_shubh.pcm" if gender == "male" else "filler_haan_shreya.pcm",
                "theek hai": "filler_theek_hai_shubh.pcm" if gender == "male" else "filler_theek_hai_shreya.pcm",
                "samajh gaya": "filler_samajh_gaya_shubh.pcm",
                "samajh gayi": "filler_samajh_gayi_shreya.pcm",
                "ek second": "filler_ek_second_shubh.pcm" if gender == "male" else "filler_ek_second_shreya.pcm",
            }
            if normalized in cache_map:
                cache_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cache")
                file_name = cache_map[normalized]
                file_path = os.path.join(cache_dir, file_name)
                if os.path.exists(file_path):
                    try:
                        logger.info(f"Voice Cache HIT for phrase: '{normalized}' (file: {file_name})")
                        with open(file_path, "rb") as f:
                            return f.read()
                    except Exception as e:
                        logger.warning("Failed to read cached voice file: %s", e)
            return None

        # Async worker task to generate TTS and populate target queue
        tts_first_byte_marked = False

        async def generate_and_feed(text_to_synth: str, index: int, target_queue: asyncio.Queue):
            nonlocal tts_first_byte_marked
            try:
                logger.info(f"[TTS_STREAM_STARTED] Starting TTS generation for index {index}: '{text_to_synth[:55]}'")
                # 1. Voice Cache Lookup
                cached_bytes = check_voice_cache(text_to_synth)
                if cached_bytes:
                    if self.is_twilio:
                        import audioop
                        resampled, _ = audioop.ratecv(cached_bytes, 2, 1, 16000, 8000, None)
                        cached_bytes = audioop.lin2ulaw(resampled, 2)
                    if not tts_first_byte_marked:
                        tracker.mark(SARVAM_FIRST_AUDIO_BYTE)
                        tts_first_byte_marked = True
                    await target_queue.put(cached_bytes)
                    await target_queue.put(None)
                    return

                # Apply Hinglish and Gender Post-Processing
                from app.utils.post_processor import apply_hinglish_post_processing
                v_gender = self.config.get("voice_gender") or self.config.get("voice_id") or "female"
                text_to_synth = apply_hinglish_post_processing(text_to_synth, v_gender)

                # 2. TTS Generation
                routed_provider = route_tts(text_to_synth, tts_provider, language, voice_id)

                if routed_provider == "sarvam":
                    speaker = _map_sarvam_speaker(voice_id, self.config.get("voice_gender"))
                    codec = "mulaw" if self.is_twilio else "pcm"
                    if self.sarvam_tts_conn is None:
                        self.sarvam_tts_conn = WarmSarvamConnection(
                            api_key=settings.sarvam_api_key or "",
                            speaker=speaker,
                            language="hi-IN",
                            output_audio_codec=codec
                        )
                        await self.sarvam_tts_conn.connect()
                    async for audio_chunk in self.sarvam_tts_conn.speak(text_to_synth):
                        if self.barge_in_event.is_set():
                            break
                        if not tts_first_byte_marked:
                            tracker.mark(SARVAM_FIRST_AUDIO_BYTE)
                            tts_first_byte_marked = True
                        await target_queue.put(audio_chunk)
                else:
                    if self.tts_conn is None:
                        enc = "mulaw" if self.is_twilio else "linear16"
                        sr = 8000 if self.is_twilio else 16000
                        dg_voice = _resolve_deepgram_voice(voice_id, self.config.get("voice_gender"))
                        self.tts_conn = WarmTTSConnection(
                            api_key=settings.deepgram_api_key or "",
                            voice_id=dg_voice,
                            encoding=enc,
                            sample_rate=sr
                        )
                        await self.tts_conn.connect()
                    async for audio_chunk in self.tts_conn.speak(text_to_synth):
                        if self.barge_in_event.is_set():
                            break
                        if not tts_first_byte_marked:
                            tracker.mark(SARVAM_FIRST_AUDIO_BYTE)
                            tts_first_byte_marked = True
                        await target_queue.put(audio_chunk)
            except Exception as e:
                logger.error("TTS pipeline error for index %d: %s", index, e)
            finally:
                await target_queue.put(None)
                logger.info(f"[TTS_COMPLETED] Finished TTS generation for index {index}")

        # Submit chunk helper
        first_tts_chunk_sent_marked = False

        def submit_chunk(text_chunk: str):
            nonlocal task_index, first_tts_chunk_sent_marked
            if not text_chunk.strip():
                return
            if not first_tts_chunk_sent_marked:
                tracker.mark(FIRST_TTS_CHUNK_SENT)
                first_tts_chunk_sent_marked = True
            
            queue = asyncio.Queue()
            chunk_queues[task_index] = queue
            self.tts_tasks.append(
                asyncio.create_task(generate_and_feed(text_chunk.strip(), task_index, queue))
            )
            task_index += 1

        # ── Optional Immediate Cached Filler Fallback ──────────────────
        if voice_cfg.ENABLE_FILLER_RESPONSE and tts_provider == "sarvam":
            # Play cached filler immediately within 200ms
            speaker = _map_sarvam_speaker(voice_id, self.config.get("voice_gender"))
            fillers = ["ji", "haan", "theek_hai", "samajh_gaya" if speaker == "shubh" else "samajh_gayi", "ek_second"]
            import random
            chosen_filler = random.choice(fillers)
            
            cache_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cache")
            filler_path = os.path.join(cache_dir, f"filler_{chosen_filler}_{speaker}.pcm")
            if os.path.exists(filler_path):
                try:
                    with open(filler_path, "rb") as f:
                        filler_bytes = f.read()
                    logger.info(f"Immediate filler cache HIT: playing '{chosen_filler}' for speaker '{speaker}'")
                    queue = asyncio.Queue()
                    chunk_queues[0] = queue
                    await queue.put(filler_bytes)
                    await queue.put(None)
                    task_index = 1
                except Exception as e:
                    logger.warning(f"Failed to play immediate filler: {e}")

        # Start playback worker loop task
        playback_task = asyncio.create_task(playback_worker())

        try:
            # ── 1. Stream LLM tokens ──────────────────────────────────
            words: list[str] = []
            is_first_chunk = True
            
            logger.info("[LLM_RESPONSE_STARTED] Starting LLM generation")
            llm_stream = llm.generate_stream(
                system_prompt=self._build_system_prompt(),
                messages=compressed_history,
                model=model,
                temperature=0.7,
                max_tokens=voice_cfg.OPENAI_MAX_OUTPUT_TOKENS,
            )

            def ends_with_punctuation(w: str) -> bool:
                # Split on sentence or clause boundaries for natural phrasing and stable intonation
                return len(w) > 0 and w[-1] in (".", "!", "?", "।", ",", ";", ":")

            async for token in llm_stream:
                if self.barge_in_event.is_set():
                    break

                if not first_token_marked:
                    tracker.mark(LLM_FIRST_TOKEN)
                    first_token_marked = True

                token_buffer += token
                full_response += token

                await self.send_json({"type": "llm_text", "text": full_response})

                # Split the buffer into completed words
                temp_words = token_buffer.split()
                if not token.endswith(" ") and temp_words:
                    completed_words = temp_words[:-1]
                    token_buffer = temp_words[-1]
                else:
                    completed_words = temp_words
                    token_buffer = ""

                for word in completed_words:
                    words.append(word)
                    word_count = len(words)
                    
                    # First chunk: 2 words to get the fastest possible response time (lowest latency).
                    # Later chunks: 8 words to maintain continuous phrasing and stable pitch.
                    # We also split on punctuation (commas, periods, etc.) for natural pauses.
                    limit = 2 if is_first_chunk else 8
                    
                    if ends_with_punctuation(word) or word_count >= limit:
                        submit_chunk(" ".join(words))
                        words = []
                        is_first_chunk = False

            # Submit remainder from stream
            if words or token_buffer.strip():
                rem = " ".join(words)
                if token_buffer.strip():
                    rem = (rem + " " + token_buffer.strip()).strip()
                if rem:
                    submit_chunk(rem)

            stream_finished_event.set()
            logger.info(f"[LLM_COMPLETED] Finished LLM generation. Response: '{full_response}'")
            self.messages.append({"role": "assistant", "content": full_response})
            if self.call_db_id and assistant_seq:
                try:
                    from datetime import datetime, timezone
                    from app.db.client import get_supabase_client
                    def _insert_assistant_msg(seq: int):
                        db = get_supabase_client()
                        db.table("call_messages").insert({
                            "call_id": self.call_db_id,
                            "role": "assistant",
                            "content": full_response,
                            "sequence_number": seq,
                            "started_at": datetime.now(timezone.utc).isoformat(),
                            "model_used": model,
                        }).execute()
                        logger.info(f"[DB_LOG] Assistant message sequence {seq} inserted: '{full_response}'")
                    
                    asyncio.create_task(asyncio.to_thread(_insert_assistant_msg, assistant_seq))
                except Exception as e:
                    logger.error(f"[DB_LOG_ERROR] Failed to start assistant message DB insert: {e}")

            # Send custom transcript message for the greeting to the frontend/playground
            if is_greeting:
                await self.send_json({
                    "type": "transcript",
                    "text": full_response,
                    "is_final": True,
                    "speech_final": True,
                })

            # Wait for playback to finish
            await playback_task

        except asyncio.CancelledError:
            logger.info("[TTS_STREAM_STOPPED] LLM/TTS pipeline cancelled (barge-in or session end)")
            playback_task.cancel()
        except Exception as exc:
            logger.error("[ERROR_WITH_STACK_TRACE] LLM/TTS pipeline error: %s", exc, exc_info=True)
            await self.send_json({"type": "error", "message": str(exc)})
        finally:
            self.barge_in_event.clear()
            self.set_state("idle")
            logger.info("[LISTENING_AGAIN] Finished speaking, listening again")


# ─────────────────────────────────────────────────────────────
# WebSocket endpoint
# ─────────────────────────────────────────────────────────────
@router.websocket("/ws/voice")
@router.websocket("/api/v1/voice/twilio-media-stream")
async def voice_websocket(ws: WebSocket):
    await ws.accept()
    session = VoiceSession(ws)
    
    if "twilio" in ws.url.path:
        session.is_twilio = True
        
    if not session.is_twilio:
        await session.send_json({"type": "ready"})
    call_id = ws.query_params.get("call_id")
    if call_id:
        session.call_db_id = call_id
        logger.info(f"[WS_CONNECT] Loaded call_db_id from query params: {call_id}")
        
    agent_id = ws.query_params.get("agent_id")
    if agent_id:
        try:
            from app.db.client import get_supabase_client, fetch_agent_with_context
            db = get_supabase_client()
            agent = await asyncio.to_thread(fetch_agent_with_context, db, agent_id)
            if agent:
                kb_meta = agent.get("kb_metadata") or {}
                session.config = {
                    "model": agent.get("model") or voice_cfg.OPENAI_VOICE_MODEL,
                    "language": agent.get("language") or "hi-IN",
                    "voice_id": agent.get("voice_id") or "aura-asteria-en",
                    "tts_provider": kb_meta.get("tts_provider") or "deepgram",
                    "agent_system_prompt": agent.get("agent_system_prompt") or "",
                    "system_prompt": agent.get("system_prompt") or "",
                    "knowledge_base": agent.get("knowledge_base") or "",
                    "voice_gender": kb_meta.get("voice_gender") or "female",
                    "voice_speed": agent.get("voice_speed"),
                }
                logger.info(f"[AGENT_CONFIG] Loaded config for agent {agent_id}: model={session.config['model']}, lang={session.config['language']}, voice={session.config['voice_id']}, tts={session.config['tts_provider']}")
            else:
                logger.warning(f"[AGENT_CONFIG] No agent found in DB for id={agent_id}")
        except Exception as e:
            logger.error(f"[AGENT_CONFIG] Failed to load agent config for WS: {e}", exc_info=True)
    else:
        logger.warning("[AGENT_CONFIG] No agent_id in WS query params")


    stt = STTService(api_key=settings.deepgram_api_key or "")
    stt_task: Optional[asyncio.Task] = None
    latest_speech_final_transcript: str = ""

    async def _stt_task_monitor():
        try:
            while True:
                await asyncio.sleep(1.0)
                import time
                if stt_task:
                    done = stt_task.done()
                    cancelled = stt_task.cancelled()
                    exc_str = "None"
                    if done and not cancelled:
                        try:
                            exc = stt_task.exception()
                            exc_str = str(exc) if exc else "None"
                        except Exception as e:
                            exc_str = f"Error: {e}"
                    logger.info(
                        f"[STT_TASK_MONITOR] timestamp={time.time()}, stt_task: done={done}, "
                        f"cancelled={cancelled}, exception={exc_str}, queue_size={session.audio_queue.qsize()}, "
                        f"session_state={session._state}"
                    )
                else:
                    logger.info(
                        f"[STT_TASK_MONITOR] timestamp={time.time()}, stt_task: None, "
                        f"queue_size={session.audio_queue.qsize()}, session_state={session._state}"
                    )
        except asyncio.CancelledError:
            pass

    monitor_task = asyncio.create_task(_stt_task_monitor())

    # ── STT event loop (runs as background task) ───────────────
    async def _stt_loop():
        nonlocal latest_speech_final_transcript, stt_task
        language = session.config.get("language", "en-US")
        
        # Auto-detect language from voice: if voice is a Sarvam voice (non-aura) and language is en-US, override to hi-IN
        voice_id = session.config.get("voice_id", "")
        if voice_id and not voice_id.startswith("aura-") and language == "en-US":
            logger.info(f"[LANG_AUTO_DETECT] Voice '{voice_id}' is a Hindi/Sarvam voice. Overriding STT language to 'hi-IN'")
            language = "hi-IN"
            
        endpointing = voice_cfg.STT_ENDPOINTING_MS

        encoding = "mulaw" if session.is_twilio else "linear16"
        sample_rate = 8000 if session.is_twilio else 16000

        logger.info(f"[STT_LOOP_START] Starting STT loop: lang={language}, encoding={encoding}, sample_rate={sample_rate}, is_twilio={session.is_twilio}")

        try:
            async for event_type, payload in stt.stream_live(
                audio_queue=session.audio_queue,
                language=language,
                endpointing=endpointing,
                model=voice_cfg.STT_MODEL,
                encoding=encoding,
                sample_rate=sample_rate,
            ):
                if event_type == EVT_SPEECH_STARTED:
                    # Reset LatencyTracker at start of user speech turn
                    session.latency = LatencyTracker()
                    session.latency.mark(USER_SPEECH_STARTED)
                    latest_speech_final_transcript = ""  # Reset transcript at start of turn
                    if session.is_speaking():
                        logger.info("[VAD_SPEECH_STARTED] Speech detected by VAD while speaking (ignoring raw VAD for barge-in, relying on transcribed text)")

                elif event_type in (EVT_INTERIM, EVT_FINAL):
                    transcript = payload.get("transcript", "").strip()
                    await session.send_json({
                        "type": "transcript",
                        "text": transcript,
                        "is_final": payload.get("is_final", False),
                        "speech_final": False,
                    })
                    if event_type == EVT_INTERIM:
                        if not session.latency.has_event(DEEPGRAM_FIRST_INTERIM):
                            session.latency.mark(DEEPGRAM_FIRST_INTERIM)
                    if payload.get("is_final"):
                        if not session.latency.has_event(DEEPGRAM_FINAL):
                            session.latency.mark(DEEPGRAM_FINAL)

                    # Trigger transcript-based barge-in if agent is speaking
                    if voice_cfg.ENABLE_BARGE_IN and session.is_speaking() and transcript:
                        # Strip punctuation to verify there are actual characters
                        clean_text = re.sub(r'[^\w\s]', '', transcript).strip()
                        if clean_text:
                            import time
                            elapsed_speaking = time.time() - session.speaking_started_at
                            if elapsed_speaking < 1.2:
                                logger.info(f"[BARGE_IN_IGNORED] Interim/Final transcript '{transcript}' ignored because speaking just started {elapsed_speaking:.2f}s ago (AEC adaptation window)")
                            else:
                                logger.info(f"[USER_BARGE_IN_DETECTED] Barge-in triggered via transcript '{transcript}' after {elapsed_speaking:.2f}s")
                                session.barge_in_event.set()
                                await session.cancel_llm_tts()
                                await session.send_json({"type": "stop_audio"})
                                await session.send_json({"type": "turn_end"})

                elif event_type == EVT_SPEECH_FINAL:
                    transcript = payload["transcript"]
                    if not transcript.strip():
                        continue
                    session.latency.mark(USER_SPEECH_ENDED)
                    if not session.latency.has_event(DEEPGRAM_FINAL):
                        session.latency.mark(DEEPGRAM_FINAL)
                    latest_speech_final_transcript = transcript
                    session.latest_transcript = transcript
                    logger.info(f"[DEEPGRAM_FINAL_TRANSCRIPT] Final transcript received: '{transcript}'")

                    await session.send_json({
                        "type": "transcript",
                        "text": transcript,
                        "is_final": True,
                        "speech_final": True,
                    })

                    if voice_cfg.ENABLE_EARLY_EOT_LLM:
                        await session.cancel_llm_tts()
                        session.llm_tts_task = asyncio.create_task(
                            session.run_llm_tts_pipeline(transcript)
                        )

                elif event_type == EVT_UTTERANCE_END:
                    # Backup trigger if speech_final didn't fire
                    if (latest_speech_final_transcript
                            and not voice_cfg.ENABLE_EARLY_EOT_LLM):
                        await session.cancel_llm_tts()
                        session.llm_tts_task = asyncio.create_task(
                            session.run_llm_tts_pipeline(latest_speech_final_transcript)
                        )

                elif event_type == EVT_ERROR:
                    logger.error("STT error: %s", payload)
                    await session.send_json({"type": "error", "message": payload.get("message", "STT error")})
        except asyncio.CancelledError:
            logger.info("[STT_LOOP] STT loop task cancelled")
        except Exception as e:
            logger.error("[STT_LOOP] STT loop exception: %s", e, exc_info=True)
        finally:
            stt_task = None
            logger.info("[STT_LOOP] STT loop exited. Setting stt_task = None to allow automatic restart.")

    # ── Main receive loop ──────────────────────────────────────
    try:
        async for raw_msg in ws.iter_bytes() if False else []:  # placeholder
            pass
    except Exception:
        pass

    frame_count = 0
    # Real receive loop — handles both binary and text frames
    try:
        while True:
            try:
                data = await ws.receive()
            except WebSocketDisconnect as e:
                logger.info(f"WebSocket disconnected with code {getattr(e, 'code', 'unknown')} and reason {getattr(e, 'reason', 'unknown')}")
                break

            msg_type = data.get("type")

            if msg_type == "websocket.receive":
                payload_bytes = data.get("bytes")
                payload_text = data.get("text")

                if payload_bytes:
                    frame_count += 1
                    import time
                    stt_task_status = "None"
                    if stt_task:
                        stt_task_status = f"done={stt_task.done()}, cancelled={stt_task.cancelled()}"
                    logger.info(
                        f"[AUDIO_IN_PACKET] timestamp={time.time()}, frame={frame_count}, bytes={len(payload_bytes)}, "
                        f"queue_size={session.audio_queue.qsize()}, stt_task={stt_task_status}, state={session._state}"
                    )
                    # Audio chunk — forward to Deepgram STT
                    if stt_task is None:
                        # Start STT once we have a config
                        if session.config:
                            session.latency.mark(AUDIO_RECEIVED)
                            stt_task = asyncio.create_task(_stt_loop())
                    try:
                        session.audio_queue.put_nowait(payload_bytes)
                    except asyncio.QueueFull:
                        logger.warning(f"[AUDIO_IN_PACKET] Drop frame due to full queue at timestamp={time.time()}")
                        pass  # Drop if overwhelmed

                elif payload_text:
                    try:
                        ctrl = json.loads(payload_text)
                    except Exception:
                        continue

                    ctrl_type = ctrl.get("type")
                    ctrl_event = ctrl.get("event")

                    if ctrl_event:
                        if ctrl_event == "connected":
                            session.is_twilio = True
                            logger.info("Twilio connected event received")
                        elif ctrl_event == "start":
                            session.is_twilio = True
                            session.stream_sid = ctrl.get("streamSid", "")
                            start_data = ctrl.get("start", {})
                            call_sid = start_data.get("callSid", "unknown")
                            logger.info(f"Twilio start event: streamSid={session.stream_sid}, callSid={call_sid}")
                            
                            # Retrieve custom parameters sent in TeXML/TwiML Stream Parameter nouns
                            custom_params = start_data.get("customParameters", {})
                            agent_id_from_msg = custom_params.get("agent_id")
                            call_id_from_msg = custom_params.get("call_id")
                            
                            if agent_id_from_msg:
                                logger.info(f"[WS_START] Loading config for agent {agent_id_from_msg} from customParameters")
                                try:
                                    from app.db.client import get_supabase_client, fetch_agent_with_context
                                    db = get_supabase_client()
                                    agent = await asyncio.to_thread(fetch_agent_with_context, db, agent_id_from_msg)
                                    if agent:
                                        kb_meta = agent.get("kb_metadata") or {}
                                        session.config = {
                                            "model": agent.get("model") or voice_cfg.OPENAI_VOICE_MODEL,
                                            "language": agent.get("language") or "hi-IN",
                                            "voice_id": agent.get("voice_id") or "aura-asteria-en",
                                            "tts_provider": kb_meta.get("tts_provider") or "deepgram",
                                            "agent_system_prompt": agent.get("agent_system_prompt") or "",
                                            "system_prompt": agent.get("system_prompt") or "",
                                            "knowledge_base": agent.get("knowledge_base") or "",
                                            "voice_gender": kb_meta.get("voice_gender") or "female",
                                        }
                                        logger.info(f"[AGENT_CONFIG] Dynamically loaded config for agent {agent_id_from_msg}: model={session.config['model']}, lang={session.config['language']}, voice={session.config['voice_id']}, tts={session.config['tts_provider']}")
                                    else:
                                        logger.warning(f"[AGENT_CONFIG] No agent found in DB for id={agent_id_from_msg} from customParameters")
                                except Exception as e:
                                    logger.error(f"[AGENT_CONFIG] Failed to dynamically load agent config for WS: {e}", exc_info=True)
                            
                            if call_id_from_msg and call_id_from_msg != "None":
                                session.call_db_id = call_id_from_msg
                                logger.info(f"[WS_START] Loaded call_db_id from customParameters: {call_id_from_msg}")
                            
                            # Lookup call_db_id in DB if not set
                            if not session.call_db_id:
                                try:
                                    from app.db.client import get_supabase_client
                                    db = get_supabase_client()
                                    def _get_call():
                                        return db.table("calls").select("id").eq("twilio_call_sid", call_sid).execute()
                                    call_res = await asyncio.to_thread(_get_call)
                                    if call_res.data:
                                        session.call_db_id = call_res.data[0]["id"]
                                        logger.info(f"[WS_START] Matched callSid={call_sid} to call_db_id={session.call_db_id}")
                                    else:
                                        logger.warning(f"[WS_START] No call record in DB for callSid={call_sid}")
                                except Exception as e:
                                    logger.error(f"[WS_START_ERROR] Failed to lookup call by callSid={call_sid}: {e}")

                            # Update call status in DB to in_progress
                            if session.call_db_id:
                                try:
                                    from datetime import datetime, timezone
                                    from app.db.client import get_supabase_client
                                    db = get_supabase_client()
                                    def _update_call():
                                        db.table("calls").update({
                                            "status": "in_progress",
                                            "started_at": datetime.now(timezone.utc).isoformat()
                                        }).eq("id", session.call_db_id).execute()
                                    asyncio.create_task(asyncio.to_thread(_update_call))
                                    logger.info(f"[WS_START] Updated call status to in_progress in DB for call_id={session.call_db_id}")
                                except Exception as e:
                                    logger.error(f"[WS_START_ERROR] Failed to update call status to in_progress in DB: {e}")

                            # Provide default config for Twilio since it doesn't send "config"
                            if not session.config:
                                session.config = {
                                    "model": voice_cfg.OPENAI_VOICE_MODEL,
                                    "language": "hi-IN",
                                    "voice_id": "aura-asteria-en",
                                }
                            if session.tts_conn is None:
                                dg_voice = _resolve_deepgram_voice(
                                    session.config.get("voice_id"),
                                    session.config.get("voice_gender")
                                )
                                session.tts_conn = WarmTTSConnection(
                                    api_key=settings.deepgram_api_key or "",
                                    voice_id=dg_voice,
                                    encoding="mulaw",
                                    sample_rate=8000
                                )
                                asyncio.create_task(session.tts_conn.connect())
                            
                            if stt_task is None:
                                session.latency.mark(AUDIO_RECEIVED)
                                stt_task = asyncio.create_task(_stt_loop())

                            # Trigger initial greeting asynchronously without waiting for user speech
                            asyncio.create_task(session.trigger_initial_greeting())

                        elif ctrl_event == "media":
                            payload_b64 = ctrl.get("media", {}).get("payload")
                            if payload_b64:
                                import base64
                                audio_bytes = base64.b64decode(payload_b64)
                                frame_count += 1
                                if frame_count == 1 or frame_count % 100 == 0:
                                    logger.info(f"[TWILIO_MEDIA] Received Twilio media frame {frame_count}, {len(audio_bytes)} bytes, queue_size={session.audio_queue.qsize()}")
                                try:
                                    session.audio_queue.put_nowait(audio_bytes)
                                except asyncio.QueueFull:
                                    pass

                        elif ctrl_event == "stop":
                            stop_data = ctrl.get("stop", {})
                            logger.info(f"Twilio stop event received for streamSid={session.stream_sid}, details: {stop_data}")
                            break
                            
                        elif ctrl_event == "mark":
                            logger.info(f"Twilio mark reached: {ctrl.get('mark', {}).get('name')}")
                            
                    elif ctrl_type == "config":
                        session.config = ctrl
                        logger.info(
                            "Voice session configured: model=%s voice=%s lang=%s",
                            ctrl.get("model"), ctrl.get("voice_id"), ctrl.get("language"),
                        )
                        # Pre-warm TTS connection in the background
                        voice_id = ctrl.get("voice_id") or "aura-asteria-en"
                        tts_provider = ctrl.get("tts_provider") or "deepgram"
                        language = ctrl.get("language") or "en-US"
                        early_provider = route_tts("", tts_provider, language, voice_id)

                        if early_provider == "sarvam":
                            speaker = _map_sarvam_speaker(voice_id, ctrl.get("voice_gender"))
                            codec = "mulaw" if session.is_twilio else "pcm"
                            if session.sarvam_tts_conn is None:
                                session.sarvam_tts_conn = WarmSarvamConnection(
                                    api_key=settings.sarvam_api_key or "",
                                    speaker=speaker,
                                    language="hi-IN",
                                    output_audio_codec=codec
                                )
                                logger.info("[PRE_WARM] Pre-warming Sarvam WS connection from config in the background...")
                                asyncio.create_task(session.sarvam_tts_conn.connect())
                        else:
                            if session.tts_conn is None:
                                dg_voice = _resolve_deepgram_voice(voice_id, ctrl.get("voice_gender"))
                                session.tts_conn = WarmTTSConnection(
                                    api_key=settings.deepgram_api_key or "",
                                    voice_id=dg_voice,
                                )
                                logger.info("[PRE_WARM] Pre-warming Deepgram WS connection from config in the background...")
                                asyncio.create_task(session.tts_conn.connect())

                        # Start STT now that we have config
                        if stt_task is None:
                            session.latency.mark(AUDIO_RECEIVED)
                            stt_task = asyncio.create_task(_stt_loop())

                    elif ctrl_type == "barge_in":
                        logger.info("Barge-in from frontend")
                        session.barge_in_event.set()
                        await session.cancel_llm_tts()
                        await session.send_json({"type": "stop_audio"})
                        await session.send_json({"type": "turn_end"})

                    elif ctrl_type == "end_session":
                        break

            elif msg_type == "websocket.disconnect":
                break

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.error("[ERROR_WITH_STACK_TRACE] Voice WS error: %s", exc, exc_info=True)
    finally:
        # Cleanup
        if monitor_task:
            monitor_task.cancel()
        await session.audio_queue.put(None)  # Signal STT to close
        await session.cancel_llm_tts()
        if session.tts_conn:
            await session.tts_conn.close()
        if session.sarvam_tts_conn:
            await session.sarvam_tts_conn.close()
        await session.sarvam_tts.close()
        if stt_task:
            stt_task.cancel()

        # Update call status in DB on WebSocket disconnect
        if session.call_db_id:
            try:
                from datetime import datetime, timezone
                from app.db.client import get_supabase_client
                db = get_supabase_client()
                
                def _update_call_end():
                    res = db.table("calls").select("status, started_at").eq("id", session.call_db_id).execute()
                    if res.data:
                        current = res.data[0]
                        status = current.get("status")
                        if status not in ("completed", "failed", "no-answer", "no_answer", "canceled", "busy"):
                            now = datetime.now(timezone.utc)
                            update_data = {
                                "status": "completed",
                                "ended_at": now.isoformat()
                            }
                            started_at_str = current.get("started_at")
                            if started_at_str:
                                try:
                                    if started_at_str.endswith("Z"):
                                        started_at_str = started_at_str[:-1] + "+00:00"
                                    started_dt = datetime.fromisoformat(started_at_str)
                                    duration_seconds = int((now - started_dt).total_seconds())
                                    update_data["actual_duration"] = max(0, duration_seconds)
                                except Exception as dur_err:
                                    logger.warning(f"Failed to calculate call duration on WS disconnect: {dur_err}")
                            
                            db.table("calls").update(update_data).eq("id", session.call_db_id).execute()
                            logger.info(f"[WS_DISCONNECT] Updated call status to completed in DB for call_id={session.call_db_id}")
                            
                asyncio.create_task(asyncio.to_thread(_update_call_end))
            except Exception as e:
                logger.error(f"[WS_DISCONNECT_ERROR] Failed to update call status to completed in DB: {e}")

        logger.info("Voice WS disconnected")


@router.get("/api/test-llm")
async def test_llm_endpoint():
    from app.db.client import get_supabase_client, fetch_agent_with_context
    db = get_supabase_client()
    agent_id = "fee34fc7-1c3d-4554-9c81-da4111df3651"
    agent = await asyncio.to_thread(fetch_agent_with_context, db, agent_id)
    kb_meta = agent.get("kb_metadata") or {}
    
    config = {
        "model": agent.get("model") or "gpt-4o-mini",
        "language": agent.get("language") or "hi-IN",
        "voice_id": agent.get("voice_id") or "aura-asteria-en",
        "tts_provider": kb_meta.get("tts_provider") or "deepgram",
        "agent_system_prompt": agent.get("agent_system_prompt") or "",
        "system_prompt": agent.get("system_prompt") or "",
        "knowledge_base": agent.get("knowledge_base") or "",
        "voice_gender": kb_meta.get("voice_gender") or "female",
    }
    
    # Create dummy session
    from fastapi import WebSocket
    class DummyWebSocket:
        async def send_json(self, data): pass
        async def send_bytes(self, data): pass
    session = VoiceSession(DummyWebSocket())
    session.config = config
    sys_prompt = session._build_system_prompt()
    
    prompt_instruction = "Generate a short, friendly, conversational welcome greeting for the caller to start the call. Speak in Roman Hinglish (mix of Hindi/English)."
    messages = [{"role": "user", "content": prompt_instruction}]
    
    llm = LLMService(
        openai_key=settings.openai_api_key,
    )
    
    tokens = []
    async for token in llm.generate_stream(
        system_prompt=sys_prompt,
        messages=messages,
        model=config["model"],
        temperature=0.7,
        max_tokens=80
    ):
        tokens.append(token)
    
    return {"status": "success", "tokens": "".join(tokens)}
