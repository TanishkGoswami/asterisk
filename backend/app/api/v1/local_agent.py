from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, Response
from pydantic import BaseModel

from app.db.client import Client, get_db
from app.services.local_agent_service import (
    DEFAULT_PROMPT,
    DEFAULT_VOICE_ID,
    LocalAgentService,
)


router = APIRouter()
service = LocalAgentService()


class KnowledgeBaseUpdateRequest(BaseModel):
    content: str


@router.get("/local-agent/config")
async def get_local_agent_config(response: Response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    capabilities = service.get_capabilities()
    capabilities["default_prompt"] = DEFAULT_PROMPT
    return capabilities


@router.get("/local-agent/knowledge-base")
async def get_knowledge_base():
    return {
        "content": service.read_knowledge_base(),
        "path": str(service.knowledge_base_path),
    }


@router.put("/local-agent/knowledge-base")
async def update_knowledge_base(payload: KnowledgeBaseUpdateRequest):
    service.write_knowledge_base(payload.content)
    return {
        "ok": True,
        "path": str(service.knowledge_base_path),
        "length": len(payload.content),
    }


@router.post("/local-agent/test")
async def test_local_agent(
    text: Optional[str] = Form(None),
    audio: Optional[UploadFile] = File(None),
    language: str = Form("en-US"),
    model: str = Form("gpt-4o-mini"),
    voice_id: str = Form(DEFAULT_VOICE_ID),
    system_prompt: str = Form(DEFAULT_PROMPT),
    knowledge_base: Optional[str] = Form(None),
    agent_id: Optional[str] = Form(None),
    workspace_id: Optional[str] = Form(None),
    session_id: Optional[str] = Form(None),
    db: Client = Depends(get_db),
):
    try:
        audio_bytes = await audio.read() if audio else None
        result = await service.run_test(
            text=text,
            audio_bytes=audio_bytes,
            language=language,
            system_prompt=system_prompt,
            model=model,
            voice_id=voice_id,
            knowledge_base_text=knowledge_base if knowledge_base else None,
        )

        # Persistence (if workspace and agent IDs provided)
        if workspace_id and agent_id:
            # Enforce agent workspace ownership
            agent_check = db.table("agents").select("id").eq("id", agent_id).eq("workspace_id", workspace_id).execute()
            if not agent_check.data:
                raise HTTPException(status_code=403, detail="Agent does not belong to this workspace")

            try:
                # Create or reuse session
                if not session_id:
                    s_res = db.table("chat_sessions").insert({
                        "workspace_id": workspace_id,
                        "agent_id": agent_id,
                        "user_identifier": "Web User (Test)"
                    }).execute()
                    session_id = s_res.data[0]["id"]

                # Return session_id before attempting message save so it's
                # always echoed back even if the insert below fails
                result["session_id"] = session_id

                db.table("chat_messages").insert([
                    {"session_id": session_id, "role": "user", "content": result["transcript"]},
                    {"session_id": session_id, "role": "assistant", "content": result["response_text"]}
                ]).execute()
            except Exception as e:
                import logging
                logging.getLogger(__name__).error(f"Failed to save local test history: {e}")

        return result
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

test_router = APIRouter()

class SarvamTestRequest(BaseModel):
    text: str
    language: str = "hi-IN"
    speaker: str = "shubh"
    voice_gender: str = "male"

class RouterTestRequest(BaseModel):
    text: str
    language: str = "auto"

@test_router.post("/sarvam-tts")
async def test_sarvam_tts(payload: SarvamTestRequest):
    from app.services.sarvam_tts import SarvamTTSService
    from app.core.config import settings
    import time
    import base64

    start_time = time.monotonic()
    try:
        from app.api.v1.voice_ws import _map_sarvam_speaker
        sarvam = SarvamTTSService(settings.sarvam_api_key or "")
        resolved_speaker = _map_sarvam_speaker(payload.speaker, payload.voice_gender)
        audio_bytes = await sarvam.convert_text_to_speech(
            text=payload.text,
            speaker=resolved_speaker,
            language=payload.language,
            output_audio_codec="mp3"
        )
        latency = int((time.monotonic() - start_time) * 1000)
        return {
            "audio_base64": base64.b64encode(audio_bytes).decode("utf-8"),
            "audio": base64.b64encode(audio_bytes).decode("utf-8"),
            "provider_used": "Sarvam",
            "provider": "Sarvam",
            "latency_ms": latency
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))

@test_router.post("/tts-router")
async def test_tts_router(payload: RouterTestRequest):
    from app.services.tts_router import route_tts
    from app.services.sarvam_tts import SarvamTTSService
    from app.services.tts_service import TTSService
    from app.core.config import settings
    import time
    import base64

    start_time = time.monotonic()
    try:
        routed_provider = route_tts(payload.text, "auto", payload.language)

        if routed_provider == "sarvam":
            sarvam = SarvamTTSService(settings.sarvam_api_key or "")
            audio_bytes = await sarvam.convert_text_to_speech(
                text=payload.text,
                speaker="shubh",
                language="hi-IN",
                output_audio_codec="mp3"
            )
            provider_display = "Sarvam"
        else:
            dg_tts = TTSService(settings.deepgram_api_key or "")
            audio_bytes = await dg_tts.synthesize(payload.text, voice_id="aura-asteria-en")
            provider_display = "Deepgram"

        latency = int((time.monotonic() - start_time) * 1000)
        return {
            "audio_base64": base64.b64encode(audio_bytes).decode("utf-8"),
            "audio": base64.b64encode(audio_bytes).decode("utf-8"),
            "provider_used": provider_display,
            "provider": provider_display,
            "latency_ms": latency
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
