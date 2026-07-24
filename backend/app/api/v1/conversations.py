"""
Voice agent conversation endpoint — modeled on the GAP calling assistant pattern.
POST /api/v1/agents/{agent_id}/ask  ->  audio/text -> STT -> LLM -> TTS -> JSON response
"""
import base64
import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from app.db.client import get_db, Client, fetch_agent_with_context
from app.core.config import settings
from app.services.stt_service import STTService
from app.services.llm_service import LLMService
from app.services.tts_service import TTSService

router = APIRouter()
logger = logging.getLogger(__name__)

STOP_PHRASES = {
    "stop", "bye", "goodbye", "end call", "hang up", "cut the call",
    "band karo", "call cut karo", "bas", "exit", "quit",
}

# ---------- Service singletons (lazy init) ----------

_stt: Optional[STTService] = None
_llm: Optional[LLMService] = None
_tts: Optional[TTSService] = None


def _get_stt() -> Optional[STTService]:
    global _stt
    if _stt is None and settings.deepgram_api_key:
        _stt = STTService(api_key=settings.deepgram_api_key)
    return _stt


def _get_llm() -> Optional[LLMService]:
    global _llm
    if _llm is None and settings.openai_api_key:
        _llm = LLMService(
            openai_key=settings.openai_api_key,
        )
    return _llm


def _get_tts() -> Optional[TTSService]:
    global _tts
    if _tts is None and settings.deepgram_api_key:
        _tts = TTSService(api_key=settings.deepgram_api_key)
    return _tts


# ---------- Endpoints ----------

@router.get("/{workspace_id}/sessions")

async def list_sessions(workspace_id: str, db: Client = Depends(get_db)):
    """List all chat sessions in a workspace"""
    result = db.table("chat_sessions").select("*, agents(name)").eq("workspace_id", workspace_id).order("created_at", desc=True).execute()
    # Flatten agent name
    for item in result.data:
        if item.get("agents"):
            item["agent_name"] = item["agents"]["name"]
    return result.data


@router.get("/sessions/{session_id}/messages")
async def get_session_messages(session_id: str, db: Client = Depends(get_db)):
    """Get all messages for a specific session"""
    result = db.table("chat_messages").select("*").eq("session_id", session_id).order("created_at").execute()
    return result.data


@router.post("/{agent_id}/ask")
async def agent_ask(
    agent_id: str,
    audio: Optional[UploadFile] = File(None),
    text: Optional[str] = Form(None),
    session_id: Optional[str] = Form(None),
    db: Client = Depends(get_db),
):
    """
    Core voice loop (same pattern as GAP):
      audio OR text  ->  STT  ->  LLM  ->  TTS  ->  {stt, answer, audio_b64, should_stop}
    """
    # 1. Load agent config from DB
    agent = fetch_agent_with_context(db, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    workspace_id = agent.get("workspace_id")

    system_prompt = (agent.get("agent_system_prompt") or agent.get("system_prompt") or "You are a helpful voice assistant. Be concise.").strip()
    language = agent.get("language", "en-US")
    voice_id = agent.get("voice_id", "aura-asteria-en")
    model = agent.get("model", "gpt-4o-mini")
    temperature = float(agent.get("temperature", 0.7))
    kb_metadata = agent.get("kb_metadata") or {}
    tts_provider = kb_metadata.get("tts_provider") or "deepgram"
    voice_gender = kb_metadata.get("voice_gender")

    # 2. Resolve user text
    user_text = (text or "").strip()
    stt_text = ""

    if not user_text and audio is not None:
        stt = _get_stt()
        if stt:
            try:
                audio_bytes = await audio.read()
                stt_text = await asyncio.to_thread(
                    stt.transcribe_bytes, audio_bytes, language
                )
                user_text = stt_text
            except Exception as e:
                logger.error(f"STT failed: {e}")

    # 3. No speech detected
    if not user_text:
        no_input_msg = "I didn't catch that — could you please repeat?"
        audio_b64 = await _tts_b64(
            voice_id=voice_id,
            text=no_input_msg,
            tts_provider=tts_provider,
            language=language,
            voice_gender=voice_gender,
            voice_speed=agent.get("voice_speed")
        )
        return {
            "stt": "", "answer": no_input_msg,
            "audio_b64": audio_b64, "should_stop": False, "no_input": True,
        }

    # 4. Stop phrases
    if any(p in user_text.lower() for p in STOP_PHRASES):
        return {
            "stt": user_text, "answer": "Call ended. Thank you!",
            "audio_b64": "", "should_stop": True, "no_input": False,
        }

    # 5. LLM response
    llm = _get_llm()
    if llm:
        try:
            answer = await llm.generate(
                system_prompt=system_prompt,
                messages=[{"role": "user", "content": user_text}],
                model=model,
                temperature=temperature,
            )
        except Exception as e:
            logger.error(f"LLM failed: {e}")
            answer = "I'm having trouble right now. Please try again."
    else:
        answer = "LLM service not configured."

    # 6. TTS
    audio_b64 = await _tts_b64(
        voice_id=voice_id,
        text=answer,
        tts_provider=tts_provider,
        language=language,
        voice_gender=voice_gender,
        voice_speed=agent.get("voice_speed")
    )

    # 7. Persistence
    try:
        # Create or verify session
        if not session_id:
            s_res = db.table("chat_sessions").insert({
                "workspace_id": workspace_id,
                "agent_id": agent_id,
                "user_identifier": "Web User"
            }).execute()
            session_id = s_res.data[0]["id"]
        
        # Save messages
        db.table("chat_messages").insert([
            {"session_id": session_id, "role": "user", "content": user_text},
            {"session_id": session_id, "role": "assistant", "content": answer}
        ]).execute()
    except Exception as e:
        logger.error(f"Failed to save chat history: {e}")

    return {
        "stt": stt_text, "answer": answer,
        "audio_b64": audio_b64, "should_stop": False, "no_input": False,
        "session_id": session_id
    }



async def _tts_b64(
    voice_id: str,
    text: str,
    tts_provider: str = "deepgram",
    language: str = "en-US",
    voice_gender: Optional[str] = None,
    voice_speed: Optional[float] = None
) -> str:
    from app.services.tts_router import route_tts
    routed_provider = route_tts(text, tts_provider, language, voice_id)

    try:
        if routed_provider == "sarvam":
            from app.services.sarvam_tts import SarvamTTSService
            sarvam = SarvamTTSService(settings.sarvam_api_key or "")
            from app.api.v1.webhooks import _map_sarvam_speaker
            speaker = _map_sarvam_speaker(voice_id, voice_gender)
            sarvam_lang = "en-IN" if language.lower().startswith("en") else "hi-IN"
            speed = float(voice_speed or 0.95)
            speed = max(0.5, min(2.0, speed))
            audio_bytes = await sarvam.convert_text_to_speech(
                text=text,
                speaker=speaker,
                language=sarvam_lang,
                output_audio_codec="mp3",
                pace=speed
            )
        else:
            tts = _get_tts()
            if not tts:
                return ""
            audio_bytes = await tts.synthesize(text, voice_id=voice_id)
        return base64.b64encode(audio_bytes).decode()
    except Exception as e:
        logger.error(f"TTS failed: {e}")
        return ""
