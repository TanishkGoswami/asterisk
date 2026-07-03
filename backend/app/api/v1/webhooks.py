from datetime import datetime, timezone
import asyncio
import logging
from urllib.parse import urlparse
import xml.etree.ElementTree as ET

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response, StreamingResponse

from app.core.config import settings
from app.db.client import Client, get_db, fetch_agent_with_context
from app.services.llm_service import LLMService
from app.services.schedule_parser import ScheduleParserService

logger = logging.getLogger(__name__)

def _map_sarvam_speaker(voice_id: str) -> str:
    voice_lower = voice_id.lower() if voice_id else ""
    for spk in ["shubh", "shreya", "manan", "ishita", "arjun"]:
        if spk in voice_lower:
            return spk
    if any(g in voice_lower for g in ["asteria", "luna", "stella", "athena", "hera", "thalia", "amalthea", "female"]):
        return "shreya"
    return "shubh"


router = APIRouter()

# Simple in-memory agent cache with 60s TTL
import time
_agent_cache: dict[str, tuple[float, dict]] = {}
AGENT_CACHE_TTL = 60.0  # seconds

async def _get_cached_agent(db: Client, agent_id: str) -> dict:
    now = time.time()
    if agent_id in _agent_cache:
        timestamp, agent = _agent_cache[agent_id]
        if now - timestamp < AGENT_CACHE_TTL:
            return agent

    agent = await asyncio.to_thread(
        fetch_agent_with_context, db, agent_id
    )
    if not agent:
        raise ValueError(f"Agent {agent_id} not found")
    _agent_cache[agent_id] = (now, agent)
    return agent


def _public_base_url(request: Request = None) -> str:
    """Derive the publicly reachable base URL from settings, request, or webhook URLs."""
    if settings.public_base_url:
        return settings.public_base_url.rstrip("/")
    if request:
        # Check X-Forwarded-Proto header first for HTTPS proxies
        proto = request.headers.get("x-forwarded-proto") or request.url.scheme
        host = request.headers.get("x-forwarded-host") or request.url.netloc
        return f"{proto}://{host}"
    webhook_url = settings.telnyx_webhook_url or settings.twilio_webhook_url or ""
    if webhook_url:
        parsed = urlparse(webhook_url)
        return f"{parsed.scheme}://{parsed.netloc}"
    return ""


def _gather_url(call_id: str, agent_id: str, request: Request = None) -> str:
    return f"{_public_base_url(request)}/api/webhooks/telnyx/gather?call_id={call_id}&agent_id={agent_id}"


def _normalize_phone(phone: str) -> str:
    return phone.replace(" ", "").replace("-", "").replace("(", "").replace(")", "")


def _build_agent_prompt(agent: dict) -> str:
    """Always inject the live knowledge_base field, stripping any stale compiled KB."""
    base_prompt = (agent.get("agent_system_prompt") or agent.get("system_prompt") or "You are a helpful voice assistant.").strip()
    knowledge_base = (agent.get("knowledge_base") or "").strip()

    # Strip any previously compiled KB section so we never use stale content
    for marker in ("--- Latest Knowledge Base ---", "--- Knowledge Base ---"):
        if marker in base_prompt:
            base_prompt = base_prompt.split(marker)[0].strip()

    # Resolve active gender
    kb_metadata = agent.get("kb_metadata") or {}
    voice_gender = kb_metadata.get("voice_gender")
    voice_id = agent.get("voice_id")
    from app.utils.post_processor import detect_voice_gender
    from app.api.v1.voice_ws import _get_male_persona_block, _get_female_persona_block
    gender = voice_gender.lower() if voice_gender else detect_voice_gender(voice_id)

    # Swap the Voice Agent Persona block dynamically to match the current gender
    if "--- Voice Agent Persona ---" in base_prompt:
        parts = base_prompt.split("--- Voice Agent Persona ---")
        header = parts[0].strip()
        persona_block = _get_male_persona_block() if gender == "male" else _get_female_persona_block()
        base_prompt = f"{header}\n\n{persona_block}"
    else:
        # Fallback: inject a full persona block even when the marker is absent
        persona_block = _get_male_persona_block() if gender == "male" else _get_female_persona_block()
        base_prompt += f"\n\n{persona_block}"

    voice_instruction = (
        "You are a real-time voice assistant on a phone call. You MUST answer in short Hinglish. "
        "Maximum response length: 1–2 sentences. Avoid long explanations. "
        "Use natural spoken language. Never generate paragraphs for voice calls. "
        "NEVER use bullet points, numbered lists, or list multiple options."
    )

    if knowledge_base:
        return f"{base_prompt}\n\n{voice_instruction}\n\n--- Knowledge Base ---\n{knowledge_base}"

    logger.warning("Agent %s has no knowledge_base field set", agent.get("id"))
    return f"{base_prompt}\n\n{voice_instruction}"


async def _request_params(request: Request) -> dict:
    params = dict(request.query_params)
    if request.method != "GET":
        # Try JSON first (Telnyx mostly uses JSON for Call Control webhooks)
        try:
            json_data = await request.json()
            if isinstance(json_data, dict):
                # Telnyx puts things inside `data.payload` sometimes, but we'll merge the top level
                params.update(json_data)
        except Exception:
            pass
        
        # Then try form data (Twilio and Telnyx TeXML)
        try:
            form_data = await request.form()
            params.update(dict(form_data))
        except Exception:
            pass
    return params


def _xml_response(root: ET.Element) -> Response:
    xml_content = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    return Response(content=xml_content, media_type="application/xml")


def _hangup(parent: ET.Element) -> ET.Element:
    return ET.SubElement(parent, "Hangup")


def _say(parent: ET.Element, text: str, request: Request = None) -> ET.Element:
    """Generate a Play tag to avoid Twilio TTS charges."""
    from urllib.parse import quote_plus
    play_url = f"{_public_base_url(request)}/api/webhooks/play-audio?text={quote_plus(text)}&provider=deepgram"
    play_node = ET.SubElement(parent, "Play")
    play_node.text = play_url
    return play_node


from typing import Optional

@router.get("/play-audio")
async def play_audio(
    text: Optional[str] = None,
    text_hash: Optional[str] = None,
    provider: str = "deepgram",
    voice: str = "aura-asteria-en",
    voice_gender: str = "female",
):
    """
    Synthesize text on the fly and return binary audio (MP3) for <Play> tag.
    Uses buffered (non-streaming) synthesis so that Telnyx/Twilio always gets
    a complete, valid audio response — no broken mid-stream errors.
    """
    import hashlib
    import os
    try:
        from app.services.sarvam_tts import SarvamTTSService
        from app.services.tts_service import TTSService

        if text_hash:
            from app.voice_config import _long_text_cache
            text = _long_text_cache.get(text_hash, "")
            if not text:
                logger.warning("text_hash %s not found in cache, using fallback phrase", text_hash)
                text = "Kripya dobara call karein."
        
        if not text:
            logger.warning("Both text and text_hash are missing or empty in play-audio request")
            text = "Kripya dobara call karein."

        # Apply post-processing before cache lookup so different variations are cached separately
        if provider == "sarvam":
            from app.utils.post_processor import apply_hinglish_post_processing
            text = apply_hinglish_post_processing(text, voice_gender)

        # ─── File-backed Audio Cache ───
        cache_key = hashlib.md5(f"{provider}_{voice}_{voice_gender}_{text}".encode("utf-8")).hexdigest()
        cache_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "cache")
        os.makedirs(cache_dir, exist_ok=True)
        cache_file = os.path.join(cache_dir, f"{cache_key}.mp3")

        if os.path.exists(cache_file):
            logger.info(f"Audio Cache HIT for key: {cache_key}, text: '{text[:50]}'")
            with open(cache_file, "rb") as f:
                audio_bytes = f.read()
            logger.info("[AUDIO_PLAYED] Audio bytes retrieved from cache and played")
            return Response(content=audio_bytes, media_type="audio/mpeg")

        logger.info(f"Audio Cache MISS for text: '{text[:50]}' - synthesizing via {provider}")
        logger.info("[TTS_STARTED] Starting TTS generation for audio playback")

        if provider == "sarvam":
            sarvam = SarvamTTSService(settings.sarvam_api_key or "")
            speaker = _map_sarvam_speaker(voice)
            # Use buffered synthesis — NOT streaming — so we get a complete audio blob
            # before sending to Telnyx. This prevents broken audio on Sarvam errors.
            audio_bytes = await sarvam.convert_text_to_speech(
                text=text,
                speaker=speaker,
                language="hi-IN",
                output_audio_codec="mp3"
            )
        else:
            dg_tts = TTSService(settings.deepgram_api_key or "")
            audio_bytes = await dg_tts.synthesize(text, voice_id=voice)

        # Save to cache
        try:
            with open(cache_file, "wb") as f:
                f.write(audio_bytes)
            logger.info(f"Saved synthesized audio to cache: {cache_file}")
        except Exception as cache_err:
            logger.warning(f"Failed to save audio to cache: {cache_err}")

        logger.info("[TTS_COMPLETED] Finished TTS generation for audio playback")
        logger.info("[AUDIO_PLAYED] Played synthesized audio bytes to client")
        return Response(content=audio_bytes, media_type="audio/mpeg")

    except Exception as exc:
        logger.error("[ERROR_WITH_STACK_TRACE] Failed to generate play-audio: %s", exc, exc_info=True)
        try:
            # Absolute fallback to Deepgram TTS
            from app.services.tts_service import TTSService
            dg_tts = TTSService(settings.deepgram_api_key or "")
            audio_bytes = await dg_tts.synthesize("Please hold on.", voice_id="aura-asteria-en")
            logger.info("[AUDIO_PLAYED] Played absolute fallback audio to client")
            return Response(content=audio_bytes, media_type="audio/mpeg")
        except Exception as fallback_exc:
            logger.error("[ERROR_WITH_STACK_TRACE] Fallback synthesis also failed: %s", fallback_exc, exc_info=True)
            return Response(content=b"", media_type="audio/mpeg")





@router.api_route("/telnyx/inbound", methods=["GET", "POST"])
@router.api_route("/twilio/inbound", methods=["GET", "POST"])
async def handle_inbound_call(request: Request, db: Client = Depends(get_db)):
    """Handle incoming call from Telnyx TeXML fetch or legacy Twilio route."""
    logger.info("[CALL_STARTED] Inbound call webhook triggered")
    
    # Pre-flight Core Services Check
    if not settings.openai_api_key or not settings.deepgram_api_key or not settings.sarvam_api_key:
        logger.error("Core services are not configured. Rejecting inbound call to prevent drop/billing.")
        root = ET.Element("Response")
        ET.SubElement(root, "Reject")
        return _xml_response(root)

    try:
        params = await _request_params(request)
        call_sid = params.get("CallSid")
        from_phone = params.get("From")
        to_phone = _normalize_phone(params.get("To", ""))

        provider = "twilio" if "twilio" in str(request.url) else "telnyx"
        logger.info("Inbound call details: %s from %s to %s via %s", call_sid, from_phone, to_phone, provider)

        phone_result = await asyncio.to_thread(
            db.table("phone_numbers").select("agent_id, workspace_id, id").eq("phone_number", to_phone).execute
        )

        if not phone_result.data:
            raw_to = params.get("To", "")
            phone_result = await asyncio.to_thread(
                db.table("phone_numbers").select("agent_id, workspace_id, id").eq("phone_number", raw_to).execute
            )

        if not phone_result.data:
            logger.error("Phone number %s not found in database", to_phone)
            root = ET.Element("Response")
            _say(root, "The number you dialed is not registered with our service.", request=request)
            _hangup(root)
            return _xml_response(root)

        phone_data = phone_result.data[0]
        agent_id = phone_data.get("agent_id")
        workspace_id = phone_data.get("workspace_id")
        phone_id = phone_data.get("id")

        if not agent_id:
            logger.error("No agent assigned to phone number %s", to_phone)
            root = ET.Element("Response")
            _say(root, "This number has no active agent assigned.", request=request)
            _hangup(root)
            return _xml_response(root)

        try:
            agent = await _get_cached_agent(db, agent_id)
        except Exception as agent_exc:
            logger.error("Failed to load agent %s: %s", agent_id, agent_exc)
            root = ET.Element("Response")
            _say(root, "Agent configuration not found. Goodbye.", request=request)
            _hangup(root)
            return _xml_response(root)

        try:
            call_insert = await asyncio.to_thread(
                db.table("calls").insert({
                    "workspace_id": workspace_id,
                    "agent_id": agent_id,
                    "phone_number_id": phone_id,
                    "caller_phone_number": from_phone,
                    "twilio_call_sid": call_sid,
                    "direction": "inbound",
                    "status": "in_progress",
                    "started_at": datetime.now().isoformat(),
                    "metadata": {"provider": provider},
                }).execute
            )
            if not call_insert.data:
                raise ValueError("Insert succeeded but returned no data")
            call_id = call_insert.data[0]["id"]
        except Exception as e:
            logger.error("Failed to create call record in DB: %s", e)
            # Use a dummy UUID or fallback so call doesn't fail completely
            call_id = "00000000-0000-0000-0000-000000000000"

        kb_metadata = agent.get("kb_metadata") or {}
        workflow_data = kb_metadata.get("workflow_data") or {}
        has_workflow = bool(workflow_data.get("nodes"))

        # We now use WebSockets for ALL calls, regardless of workflow config.
        # Workflows are executed asynchronously by the WebSocket pipeline.
        
        root = ET.Element("Response")
        
        # Build dynamic wss url for WebSocket
        # Prefer the incoming request's protocol and host to support proxy/multi-tenant setups cleanly
        proto = request.headers.get("x-forwarded-proto") or request.url.scheme
        scheme = "wss" if proto == "https" else "ws"
        host = request.headers.get("x-forwarded-host") or request.url.netloc
        
        # If accessing via localhost and a public base URL is configured, fallback to that config
        if ("localhost" in host or "127.0.0.1" in host) and settings.public_base_url:
            base = settings.public_base_url.replace("http://", "ws://").replace("https://", "wss://")
            stream_url = f"{base}/api/v1/voice/twilio-media-stream?agent_id={agent_id}&call_id={call_id}"
        else:
            stream_url = f"{scheme}://{host}/api/v1/voice/twilio-media-stream?agent_id={agent_id}&call_id={call_id}"
        
        # Connect to Twilio Media Streams
        connect = ET.SubElement(root, "Connect")
        stream = ET.SubElement(connect, "Stream")
        stream.set("url", stream_url)
        
        # Add custom parameters for agent_id and call_id to bypass URL parameter stripping in Twilio/Telnyx
        p1 = ET.SubElement(stream, "Parameter")
        p1.set("name", "agent_id")
        p1.set("value", agent_id)
        
        p2 = ET.SubElement(stream, "Parameter")
        p2.set("name", "call_id")
        p2.set("value", call_id or "")
        
        logger.info("[CALL_CONNECTED] Sending Media Stream Connect to %s", stream_url)
        return _xml_response(root)
        
    except Exception as exc:
        logger.error("[ERROR_WITH_STACK_TRACE] Error in handle_inbound_call: %s", exc, exc_info=True)
        root = ET.Element("Response")
        _hangup(root)
        return _xml_response(root)


@router.api_route("/telnyx/test-call", methods=["GET", "POST"])
@router.api_route("/twilio/test-call", methods=["GET", "POST"])
async def test_call_texml(
    request: Request,
    agent_id: str = "",
    call_db_id: str = "",
    db: Client = Depends(get_db),
):
    """Start an interactive test call that uses the real agent prompt."""
    logger.info("[CALL_STARTED] Test call webhook triggered")
    try:
        params = await _request_params(request)
        call_sid = params.get("CallSid") or request.query_params.get("CallSid")

        if not agent_id:
            root = ET.Element("Response")
            _say(root, "Agent ID is missing for this test call.", request=request)
            _hangup(root)
            return _xml_response(root)

        try:
            agent = await _get_cached_agent(db, agent_id)
        except Exception:
            root = ET.Element("Response")
            _say(root, "Agent configuration not found. Goodbye.", request=request)
            _hangup(root)
            return _xml_response(root)

        # Prefer the pre-inserted call_db_id (scheduled calls) over CallSid lookup
        call_id = None
        if call_db_id:
            call_result = await asyncio.to_thread(
                db.table("calls").select("id").eq("id", call_db_id).execute
            )
            if call_result.data:
                call_id = call_result.data[0]["id"]
                # Update with real CallSid from Twilio/Telnyx now that we have it
                if call_sid:
                    asyncio.create_task(asyncio.to_thread(
                        db.table("calls").update({"twilio_call_sid": call_sid, "status": "in_progress"}).eq("id", call_id).execute
                    ))

        if not call_id and call_sid:
            call_result = await asyncio.to_thread(
                db.table("calls").select("id").eq("twilio_call_sid", call_sid).execute
            )
            if call_result.data:
                call_id = call_result.data[0]["id"]
                try:
                    await asyncio.to_thread(
                        db.table("calls").update({
                            "status": "in_progress",
                            "started_at": datetime.now(timezone.utc).isoformat()
                        }).eq("id", call_id).execute
                    )
                except Exception as e:
                    logger.error(f"Failed to update test call started_at: {e}")

        if not call_id:
            root = ET.Element("Response")
            _say(root, "Test call session could not be found. Please try again.", request=request)
            _hangup(root)
            return _xml_response(root)

        kb_metadata = agent.get("kb_metadata") or {}
        workflow_data = kb_metadata.get("workflow_data") or {}
        has_workflow = bool(workflow_data.get("nodes"))

        # We now use WebSockets for ALL calls, regardless of workflow config.
        # Workflows are executed asynchronously by the WebSocket pipeline.
        
        root = ET.Element("Response")
        
        # Build dynamic wss url for WebSocket
        # Prefer the incoming request's protocol and host to support proxy/multi-tenant setups cleanly
        proto = request.headers.get("x-forwarded-proto") or request.url.scheme
        scheme = "wss" if proto == "https" else "ws"
        host = request.headers.get("x-forwarded-host") or request.url.netloc
        
        # If accessing via localhost and a public base URL is configured, fallback to that config
        if ("localhost" in host or "127.0.0.1" in host) and settings.public_base_url:
            base = settings.public_base_url.replace("http://", "ws://").replace("https://", "wss://")
            stream_url = f"{base}/api/v1/voice/twilio-media-stream?agent_id={agent_id}&call_id={call_id}"
        else:
            stream_url = f"{scheme}://{host}/api/v1/voice/twilio-media-stream?agent_id={agent_id}&call_id={call_id}"
        
        # Connect to Twilio Media Streams
        connect = ET.SubElement(root, "Connect")
        stream = ET.SubElement(connect, "Stream")
        stream.set("url", stream_url)
        
        # Add custom parameters for agent_id and call_id to bypass URL parameter stripping in Twilio/Telnyx
        p1 = ET.SubElement(stream, "Parameter")
        p1.set("name", "agent_id")
        p1.set("value", agent_id)
        
        p2 = ET.SubElement(stream, "Parameter")
        p2.set("name", "call_id")
        p2.set("value", call_id or "")
        
        logger.info("[CALL_CONNECTED] Sending Media Stream Connect to %s", stream_url)
        return _xml_response(root)
        
    except Exception as exc:
        logger.error("[ERROR_WITH_STACK_TRACE] Error in test_call_texml: %s", exc, exc_info=True)
        root = ET.Element("Response")
        _say(root, "We encountered an internal error. Please try again later.", request=request)
        _hangup(root)
        return _xml_response(root)


@router.api_route("/telnyx/status", methods=["GET", "POST"])
@router.api_route("/twilio/status", methods=["GET", "POST"])
async def handle_call_status(request: Request, db: Client = Depends(get_db)):
    """Handle call status callbacks from Telnyx or the legacy Twilio route."""
    params = await _request_params(request)
    call_sid = params.get("CallSid")
    call_status = params.get("CallStatus")

    logger.info("Call status update: %s -> %s", call_sid, call_status)

    update = {"status": call_status}
    if call_status in ("completed", "failed", "no-answer", "no_answer", "canceled", "busy"):
        now = datetime.now(timezone.utc)
        update["ended_at"] = now.isoformat()

        # Try to parse CallDuration from provider parameters
        call_duration = params.get("CallDuration")
        if call_duration:
            try:
                update["actual_duration"] = int(call_duration)
            except Exception:
                pass

        # Fallback: calculate from started_at in DB
        call_id = None
        metadata = {}
        if "actual_duration" not in update:
            try:
                call_res = db.table("calls").select("id, started_at, metadata").eq("twilio_call_sid", call_sid).execute()
                if call_res.data and call_res.data[0].get("started_at"):
                    call_data = call_res.data[0]
                    call_id = call_data.get("id")
                    metadata = call_data.get("metadata") or {}
                    started_at_str = call_data["started_at"]
                    if started_at_str.endswith("Z"):
                        started_at_str = started_at_str[:-1] + "+00:00"
                    started_dt = datetime.fromisoformat(started_at_str)
                    duration_seconds = int((now - started_dt).total_seconds())
                    update["actual_duration"] = max(0, duration_seconds)
            except Exception as e:
                logger.warning("Failed to calculate call duration fallback: %s", e)
        else:
            try:
                call_res = db.table("calls").select("id, metadata").eq("twilio_call_sid", call_sid).execute()
                if call_res.data:
                    call_id = call_res.data[0].get("id")
                    metadata = call_res.data[0].get("metadata") or {}
            except Exception as e:
                pass

        if call_status == "completed" and call_id:
            from app.services.cost_calculator import calculate_provider_costs
            from app.services.twilio_cost_service import fetch_actual_twilio_call_cost
            
            dur = update.get("actual_duration", 0)
            in_tokens = metadata.get("llm_input_tokens", 0)
            out_tokens = metadata.get("llm_output_tokens", 0)
            tts_chars = metadata.get("tts_characters", 0)
            
            logger.info(f"[CALL_USAGE] completed webhook received call_sid={call_sid}")
            logger.info(f"[CALL_USAGE] matched call_id={call_id}")
            logger.info(f"[CALL_USAGE] duration_seconds={dur}")
            logger.info(f"[CALL_USAGE] llm_input_tokens={in_tokens}")
            logger.info(f"[CALL_USAGE] llm_output_tokens={out_tokens}")
            logger.info(f"[CALL_USAGE] tts_characters={tts_chars}")
            
            # 1. Fetch actual twilio cost
            try:
                actual_twilio = await asyncio.to_thread(fetch_actual_twilio_call_cost, call_sid, settings.usd_to_inr)
                
                logger.info(f"[CALL_USAGE] twilio raw_price={actual_twilio.get('raw_price')}")
                logger.info(f"[CALL_USAGE] twilio price_unit={actual_twilio.get('price_unit')}")
                logger.info(f"[CALL_USAGE] twilio cost source={actual_twilio.get('source')}")
                
                cost_data = calculate_provider_costs(
                    duration_seconds=dur,
                    twilio_billable_minutes=actual_twilio.get("billable_minutes", 0),
                    stt_audio_seconds=dur,
                    llm_input_tokens=in_tokens,
                    llm_output_tokens=out_tokens,
                    tts_characters=tts_chars,
                    twilio_cost_inr=actual_twilio.get("twilio_cost_inr", 0),
                    twilio_cost_source=actual_twilio.get("source", "pending"),
                    usd_to_inr=settings.usd_to_inr,
                    deepgram_per_hour_usd=settings.deepgram_stt_per_hour_usd,
                    openai_input_per_1m_usd=settings.openai_input_per_1m_usd,
                    openai_output_per_1m_usd=settings.openai_output_per_1m_usd,
                    sarvam_per_10k_chars_inr=settings.sarvam_tts_per_10k_chars_inr,
                    credit_value_inr=settings.credit_value_inr,
                    twilio_fallback_per_min_usd=settings.twilio_outbound_per_min_usd
                )
                
                logger.info(f"[CALL_USAGE] final total_cost_inr={cost_data['total_cost_inr']}")
                
                cost_data["call_id"] = call_id
                cost_data["twilio_call_sid"] = call_sid
                cost_data["twilio_raw_price"] = actual_twilio.get("raw_price")
                cost_data["twilio_price_unit"] = actual_twilio.get("price_unit")
                cost_data["twilio_cost_source"] = actual_twilio.get("source")
                
                if cost_data["twilio_cost_source"] == "actual":
                    cost_data["cost_status"] = "final"
                    cost_data["cost_finalized_at"] = datetime.now(timezone.utc).isoformat()
                else:
                    cost_data["cost_status"] = "pending"
                
                # Upsert call usage
                logger.info("[CALL_USAGE] inserting/upserting call_usage...")
                await asyncio.to_thread(db.table("call_usage").upsert(cost_data, on_conflict="call_id").execute)
                logger.info(f"[CALL_USAGE] upsert success=True")
                
                # Wallet logic
                credits_used = cost_data["credits_used"]
                wallet_res = await asyncio.to_thread(
                    db.table("calls").select("agents(created_by)").eq("id", call_id).execute
                )
                creator_id = None
                if wallet_res.data:
                    agents_data = wallet_res.data[0].get("agents")
                    creator_id = agents_data.get("created_by") if agents_data else None
                    
                async def process_wallet_deduction():
                    if creator_id:
                        try:
                            # Idempotency check: see if a transaction for this call_id exists
                            existing = await asyncio.to_thread(
                                db.table("wallet_transactions").select("id").eq("call_id", call_id).execute
                            )
                            if not existing.data:
                                await asyncio.to_thread(
                                    db.table("wallet_transactions").insert({
                                        "user_id": creator_id,
                                        "amount": -credits_used,
                                        "type": "call_usage",
                                        "call_id": call_id,
                                        "description": "Voice call usage charge"
                                    }).execute
                                )
                                logger.info("[CALL_USAGE] wallet deducted/skipped=deducted")
                            else:
                                logger.info("[CALL_USAGE] wallet deducted/skipped=skipped (already deducted)")
                        except Exception as wallet_e:
                            logger.warning(f"Failed to insert wallet transaction: {wallet_e}")

                if cost_data["cost_status"] == "final":
                    await process_wallet_deduction()
                else:
                    logger.info("[CALL_USAGE] wallet deducted/skipped=skipped (pending)")
                    
                    async def sync_pending_twilio_cost(c_id, c_sid):
                        await asyncio.sleep(120)
                        from app.services.twilio_cost_service import fetch_actual_twilio_call_cost
                        from app.services.cost_calculator import calculate_provider_costs
                        
                        delayed_twilio = await asyncio.to_thread(fetch_actual_twilio_call_cost, c_sid, settings.usd_to_inr)
                        if delayed_twilio.get("source") == "actual":
                            # Refetch usage from db to ensure latest
                            usage_res = await asyncio.to_thread(db.table("call_usage").select("*").eq("call_id", c_id).execute)
                            if usage_res.data:
                                u_row = usage_res.data[0]
                                updated_cost_data = calculate_provider_costs(
                                    duration_seconds=u_row.get("duration_seconds", dur),
                                    twilio_billable_minutes=delayed_twilio.get("billable_minutes", 0),
                                    stt_audio_seconds=u_row.get("stt_audio_seconds", dur),
                                    llm_input_tokens=u_row.get("llm_input_tokens", in_tokens),
                                    llm_output_tokens=u_row.get("llm_output_tokens", out_tokens),
                                    tts_characters=u_row.get("tts_characters", tts_chars),
                                    twilio_cost_inr=delayed_twilio.get("twilio_cost_inr", 0),
                                    twilio_cost_source="actual",
                                    usd_to_inr=settings.usd_to_inr,
                                    deepgram_per_hour_usd=settings.deepgram_stt_per_hour_usd,
                                    openai_input_per_1m_usd=settings.openai_input_per_1m_usd,
                                    openai_output_per_1m_usd=settings.openai_output_per_1m_usd,
                                    sarvam_per_10k_chars_inr=settings.sarvam_tts_per_10k_chars_inr,
                                    credit_value_inr=settings.credit_value_inr,
                                    twilio_fallback_per_min_usd=settings.twilio_outbound_per_min_usd
                                )
                                updated_cost_data["call_id"] = c_id
                                updated_cost_data["twilio_call_sid"] = c_sid
                                updated_cost_data["twilio_raw_price"] = delayed_twilio.get("raw_price")
                                updated_cost_data["twilio_price_unit"] = delayed_twilio.get("price_unit")
                                updated_cost_data["cost_status"] = "final"
                                updated_cost_data["cost_finalized_at"] = datetime.now(timezone.utc).isoformat()
                                
                                try:
                                    await asyncio.to_thread(db.table("call_usage").upsert(updated_cost_data, on_conflict="call_id").execute)
                                    await process_wallet_deduction()
                                except Exception as e:
                                    logger.error(f"Delayed cost fetch DB error: {e}")
                    
                    asyncio.create_task(sync_pending_twilio_cost(call_id, call_sid))
            except Exception as e:
                logger.error(f"[CALL_USAGE] failed error={e}")
                logger.error(f"Failed to insert call_usage: {e}")

    try:
        await asyncio.to_thread(
            db.table("calls").update(update).eq("twilio_call_sid", call_sid).execute
        )
    except Exception as e:
        logger.error(f"Failed to update call status in db: {e}")

    return {"status": "ok"}


@router.api_route("/asterisk/inbound", methods=["GET", "POST"])
async def asterisk_inbound(request: Request, db: Client = Depends(get_db)):
    """
    Handle inbound call webhook from Asterisk PBX.
    Immediately registers the call session and returns under 200ms.
    """
    logger.info("[Asterisk Webhook] Inbound call trigger received")
    
    # 1. Gather parameters from query params and request body
    params = await _request_params(request)
    for k, v in request.query_params.items():
        if k not in params:
            params[k] = v

    caller_id = params.get("caller_id") or params.get("caller") or ""
    dialed_number = params.get("dialed_number") or params.get("dialed") or ""
    call_uuid = params.get("call_uuid") or params.get("uuid") or ""
    provider = params.get("provider") or settings.asterisk_provider_name or "asterisk"
    secret = params.get("secret") or ""

    # 2. Validate secret if configured
    if settings.asterisk_webhook_secret and secret != settings.asterisk_webhook_secret:
        logger.warning(f"[Asterisk Webhook] Unauthorized secret attempt: {secret}")
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="Invalid secret")

    if not call_uuid:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Missing call_uuid")

    # 3. Normalize dialed number and handle URL-decoded plus sign (interpreted as space)
    search_variants = []
    for raw_num in [dialed_number, _normalize_phone(dialed_number)]:
        if not raw_num:
            continue
        cleaned = raw_num.strip()
        # If it started with space, it was decoded from '+'
        if raw_num.startswith(" "):
            cleaned = "+" + cleaned
        search_variants.append(cleaned)
        
        # Add numeric digits only, and prefixed with '+'
        digits = "".join(c for c in cleaned if c.isdigit())
        if digits:
            search_variants.append(digits)
            search_variants.append("+" + digits)

    # De-duplicate
    search_variants = list(set(search_variants))
    logger.info(f"[Asterisk Webhook] Searching for phone number using variants: {search_variants}")

    # 4. Search in did_numbers table first
    did_result = await asyncio.to_thread(
        db.table("did_numbers").select("id, workspace_id, agent_id, sip_trunk_provider_id, status").in_("phone_number", search_variants).execute
    )

    sip_trunk_provider_id = None
    if did_result.data and isinstance(did_result.data, list):
        phone_data = did_result.data[0]
        if phone_data.get("status") != "active":
            logger.error(f"[Asterisk Webhook] DID number {dialed_number} is inactive")
            from app.services.call_admission_control import log_call_limit_event
            log_call_limit_event(phone_data.get("workspace_id"), phone_data.get("agent_id"), phone_data.get("sip_trunk_provider_id"), phone_data.get("id"), call_uuid, "inbound", "did_inactive", caller_id, dialed_number)
            await _create_rejected_call_record(db, call_uuid, phone_data.get("workspace_id"), phone_data.get("agent_id"), phone_data.get("id"), True, provider, caller_id, dialed_number, "did_inactive")
            return Response(content="REJECT:did_inactive", media_type="text/plain")
            
        workspace_id = phone_data.get("workspace_id")
        agent_id = phone_data.get("agent_id")
        phone_id = phone_data.get("id")
        sip_trunk_provider_id = phone_data.get("sip_trunk_provider_id")
        is_did = True
    else:
        # Fallback to phone_numbers table
        phone_result = await asyncio.to_thread(
            db.table("phone_numbers").select("id, workspace_id, agent_id, status").in_("phone_number", search_variants).execute
        )

        if not phone_result.data:
            logger.error(f"[Asterisk Webhook] Phone number variants {search_variants} not found in did_numbers or phone_numbers")
            from app.services.call_admission_control import log_call_limit_event
            log_call_limit_event(None, None, None, None, call_uuid, "inbound", "did_not_found", caller_id, dialed_number)
            return Response(content="REJECT:did_not_found", media_type="text/plain")

        phone_data = phone_result.data[0]
        if phone_data.get("status") != "active":
            logger.error(f"[Asterisk Webhook] Phone number {dialed_number} is inactive")
            from app.services.call_admission_control import log_call_limit_event
            log_call_limit_event(phone_data.get("workspace_id"), phone_data.get("agent_id"), None, phone_data.get("id"), call_uuid, "inbound", "did_inactive", caller_id, dialed_number)
            await _create_rejected_call_record(db, call_uuid, phone_data.get("workspace_id"), phone_data.get("agent_id"), phone_data.get("id"), False, provider, caller_id, dialed_number, "did_inactive")
            return Response(content="REJECT:did_inactive", media_type="text/plain")

        workspace_id = phone_data.get("workspace_id")
        agent_id = phone_data.get("agent_id")
        phone_id = phone_data.get("id")
        is_did = False

    if not agent_id:
        logger.error(f"[Asterisk Webhook] No agent assigned to phone number {dialed_number}")
        from app.services.call_admission_control import log_call_limit_event
        log_call_limit_event(workspace_id, None, sip_trunk_provider_id, phone_id, call_uuid, "inbound", "agent_not_found", caller_id, dialed_number)
        await _create_rejected_call_record(db, call_uuid, workspace_id, None, phone_id, is_did, provider, caller_id, dialed_number, "agent_not_found")
        return Response(content="REJECT:agent_not_found", media_type="text/plain")

    # 5. Call Admission Control checks
    from app.services.call_admission_control import check_and_reserve_call
    allowed, reason = await check_and_reserve_call(
        call_uuid=call_uuid,
        direction="inbound",
        workspace_id=str(workspace_id),
        agent_id=str(agent_id),
        sip_trunk_provider_id=str(sip_trunk_provider_id) if sip_trunk_provider_id else None,
        did_number_id=str(phone_id) if is_did else None,
        caller_id=caller_id,
        dialed_number=dialed_number
    )

    if not allowed:
        logger.warning(f"[Asterisk Webhook] Call admission control rejected inbound call {call_uuid}: {reason}")
        await _create_rejected_call_record(db, call_uuid, workspace_id, agent_id, phone_id, is_did, provider, caller_id, dialed_number, reason or "internal_error")
        return Response(content=f"REJECT:{reason or 'internal_error'}", media_type="text/plain")

    # 6. Create call record for allowed call
    try:
        import uuid
        db_call_id = str(uuid.uuid4())
        insert_payload = {
            "id": db_call_id,
            "call_uuid": call_uuid,
            "twilio_call_sid": call_uuid,
            "workspace_id": workspace_id,
            "agent_id": agent_id,
            "caller_phone_number": caller_id or "unknown",
            "caller_id": caller_id or "unknown",
            "dialed_number": dialed_number,
            "provider": provider,
            "direction": "inbound",
            "status": "ringing",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "metadata": {"provider": provider, "dialed_number": dialed_number}
        }
        if is_did:
            insert_payload["did_number_id"] = phone_id
            insert_payload["phone_number_id"] = None
            insert_payload["sip_trunk_provider_id"] = sip_trunk_provider_id
        else:
            insert_payload["phone_number_id"] = phone_id
            insert_payload["did_number_id"] = None

        await asyncio.to_thread(db.table("calls").insert(insert_payload).execute)
        logger.info(f"[Asterisk Webhook] Created DB call record for allowed call {call_uuid}")
    except Exception as db_exc:
        logger.error(f"[Asterisk Webhook] Failed to insert call record in DB: {db_exc}")

    # 7. Store call_uuid mapping in CallSessionManager
    from app.services.call_session_manager import call_session_manager
    call_session_manager.register_inbound_asterisk_call(
        call_uuid=call_uuid,
        caller_id=caller_id,
        dialed_number=dialed_number,
        workspace_id=str(workspace_id),
        agent_id=str(agent_id),
        phone_number_id=str(phone_id)
    )

    logger.info(f"[Asterisk Webhook] Inbound call ALLOWED and registered for UUID {call_uuid}")
    return Response(content="ALLOW", media_type="text/plain")


async def _create_rejected_call_record(db, call_uuid, workspace_id, agent_id, phone_id, is_did, provider, caller_id, dialed_number, reason):
    try:
        import uuid
        db_call_id = str(uuid.uuid4())
        insert_payload = {
            "id": db_call_id,
            "call_uuid": call_uuid,
            "twilio_call_sid": call_uuid,
            "workspace_id": workspace_id,
            "agent_id": agent_id,
            "caller_phone_number": caller_id or "unknown",
            "caller_id": caller_id or "unknown",
            "dialed_number": dialed_number,
            "provider": provider,
            "direction": "inbound",
            "status": "failed",
            "rejection_reason": reason,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "ended_at": datetime.now(timezone.utc).isoformat(),
            "metadata": {"provider": provider, "dialed_number": dialed_number, "rejection_reason": reason}
        }
        if is_did:
            insert_payload["did_number_id"] = phone_id
            insert_payload["phone_number_id"] = None
        else:
            insert_payload["phone_number_id"] = phone_id
            insert_payload["did_number_id"] = None

        await asyncio.to_thread(db.table("calls").insert(insert_payload).execute)
    except Exception as e:
        logger.error(f"[Asterisk Webhook] Failed to insert rejected call record: {e}")


