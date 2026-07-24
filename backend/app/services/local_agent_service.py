import asyncio
import base64
import logging
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.services.llm_service import LLMService
from app.services.stt_service import STTService
from app.services.tts_service import TTSService

logger = logging.getLogger(__name__)

DEFAULT_PROMPT = """You are Ekta, a young and polite voice assistant for Metabull Universe.
Use only the provided knowledge base to answer factual questions about the company.
If the answer is not present in the knowledge base, say sorry and mention that you only have the currently shared company information.
Treat pronunciations or spellings like metabool, metabol, or metavol as Metabull Universe.
Do not correct the user's pronunciation or spelling.
Keep the reply short, natural, and helpful.
"""

DEFAULT_VOICE_ID = "aura-asteria-en"

DEEPGRAM_VOICES = [
    "aura-asteria-en",
    "aura-luna-en",
    "aura-stella-en",
    "aura-athena-en",
    "aura-hera-en",
    "aura-orion-en",
    "aura-arcas-en",
    "aura-perseus-en",
    "aura-angus-en",
    "aura-orpheus-en",
    "aura-helios-en",
    "aura-zeus-en",
]


class LocalAgentService:
    def __init__(self) -> None:
        self.stt = STTService(settings.deepgram_api_key) if settings.deepgram_api_key else None
        self.tts = TTSService(settings.deepgram_api_key) if settings.deepgram_api_key else None
        self.llm = (
            LLMService(
                openai_key=settings.openai_api_key or "",
            )
            if settings.openai_api_key
            else None
        )

    @property
    def knowledge_base_path(self) -> Path:
        configured = settings.local_agent_knowledge_base_path
        if configured:
            return Path(configured).expanduser().resolve()
        return (Path(__file__).resolve().parents[3] / "GAP_calling_assistent" / "knowledge_base.txt").resolve()

    @property
    def default_model(self) -> str:
        return "gpt-4o-mini"

    @property
    def default_provider(self) -> str:
        return "openai"

    def get_capabilities(self) -> dict[str, Any]:
        available_models: list[str] = []
        if settings.openai_api_key:
            available_models.extend(["gpt-4o-mini"])

        voices = list(DEEPGRAM_VOICES)
        if settings.sarvam_api_key:
            voices.extend([
                "shubh", "meera", "shreya", "manan", "ishita", "arjun",
                "aayan", "aditya", "advait", "amit", "anand", "ashutosh",
                "dev", "gokul", "kabir", "kavitha", "kavya", "mani",
                "mohit", "neha", "pooja", "priya", "rahul", "ratan",
                "rehan", "ritu", "rohan", "roopa", "rupali", "shruti",
                "simran", "soham", "suhani", "sumit", "sunny", "tanya",
                "tarun", "varun", "vijay"
            ])

        return {
            "stt_available": self.stt is not None,
            "tts_available": self.tts is not None,
            "llm_available": self.llm is not None,
            "knowledge_base_path": str(self.knowledge_base_path),
            "default_model": self.default_model,
            "default_provider": self.default_provider,
            "default_voice_id": DEFAULT_VOICE_ID,
            "voices": voices,
            "models": available_models or [self.default_model],
        }

    def read_knowledge_base(self) -> str:
        path = self.knowledge_base_path
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")

    def write_knowledge_base(self, content: str) -> None:
        path = self.knowledge_base_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    async def transcribe_audio(self, audio_bytes: bytes, language: str = "en-US") -> str:
        if not self.stt:
            raise RuntimeError("Deepgram STT is not configured. Add DEEPGRAM_API_KEY in backend/.env.")
        return await asyncio.to_thread(self.stt.transcribe_bytes, audio_bytes, language)

    async def generate_reply(
        self,
        user_text: str,
        system_prompt: str | None = None,
        model: str | None = None,
        knowledge_base_text: str | None = None,
        language: str = "en-US",
    ) -> str:
        if not self.llm:
            raise RuntimeError("No LLM provider is configured. Add OPENAI_API_KEY in backend/.env.")

        knowledge_base = (knowledge_base_text if knowledge_base_text is not None else self.read_knowledge_base()).strip()
        prompt = (system_prompt or DEFAULT_PROMPT).strip()
        
        # Enforce Hindi/Hinglish if the language parameter specifies it
        if language and language.lower().startswith("hi"):
            prompt += "\n\nYou MUST respond in Hindi/Hinglish."
            
        full_system_prompt = (
            f"{prompt}\n\n"
            f"Knowledge base:\n{knowledge_base or 'No knowledge base has been provided yet.'}"
        )

        try:
            return await self.llm.generate(
                system_prompt=full_system_prompt,
                messages=[{"role": "user", "content": user_text}],
                model=model or self.default_model,
                temperature=0.4,
                max_tokens=220,
            )
        except Exception as exc:
            logger.error("Local agent LLM generation failed: %s", exc, exc_info=True)
            raise RuntimeError(f"LLM request failed: {exc}") from exc

    async def synthesize_reply(self, text: str, voice_id: str | None = None) -> bytes:
        if not self.tts:
            raise RuntimeError("Deepgram TTS is not configured. Add DEEPGRAM_API_KEY in backend/.env.")
        return await self.tts.synthesize(text=text, voice_id=voice_id or DEFAULT_VOICE_ID)

    async def run_test(
        self,
        text: str | None,
        audio_bytes: bytes | None,
        language: str,
        system_prompt: str | None,
        model: str | None,
        voice_id: str | None,
        knowledge_base_text: str | None = None,
        tts_provider: str = "auto",
        voice_gender: str | None = None,
    ) -> dict[str, Any]:
        transcript = (text or "").strip()
        if not transcript and audio_bytes:
            transcript = (await self.transcribe_audio(audio_bytes, language=language)).strip()

        if not transcript:
            raise RuntimeError("No transcript was produced. Try speaking more clearly or send text directly.")

        reply_text = await self.generate_reply(
            user_text=transcript,
            system_prompt=system_prompt,
            model=model,
            knowledge_base_text=knowledge_base_text,
            language=language,
        )

        from app.services.tts_router import route_tts
        from app.services.sarvam_tts import SarvamTTSService
        from app.api.v1.voice_ws import _map_sarvam_speaker
        
        routed_provider = route_tts(reply_text, tts_provider, language, voice_id)
        if routed_provider == "sarvam":
            from app.utils.post_processor import apply_hinglish_post_processing
            gender_to_use = voice_gender or voice_id or "female"
            reply_text = apply_hinglish_post_processing(reply_text, gender_to_use)
            sarvam_tts = SarvamTTSService(settings.sarvam_api_key or "")
            speaker = _map_sarvam_speaker(voice_id or "meera", voice_gender)
            # Use en-IN for Indian English accent; hi-IN for Hindi/Hinglish
            sarvam_lang = "en-IN" if language.lower().startswith("en") else "hi-IN"
            audio_output = await sarvam_tts.convert_text_to_speech(
                text=reply_text,
                speaker=speaker,
                language=sarvam_lang,
                output_audio_codec="mp3"
            )
        else:
            audio_output = await self.synthesize_reply(reply_text, voice_id=voice_id)

        kb_preview = (knowledge_base_text if knowledge_base_text is not None else self.read_knowledge_base())[:500]
        return {
            "transcript": transcript,
            "response_text": reply_text,
            "audio_base64": base64.b64encode(audio_output).decode("utf-8"),
            "knowledge_base_preview": kb_preview,
        }
