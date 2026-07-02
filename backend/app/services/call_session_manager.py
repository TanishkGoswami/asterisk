import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Callable
from app.db.client import get_supabase_client, fetch_agent_with_context
import asyncio

logger = logging.getLogger(__name__)

class CallSessionManager:
    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(CallSessionManager, cls).__new__(cls, *args, **kwargs)
            cls._instance._init()
        return cls._instance

    def _init(self):
        self.active_calls = {}
        self.cleanup_callbacks = {}

    def register_inbound_asterisk_call(
        self,
        call_uuid: str,
        caller_id: str,
        dialed_number: str,
        workspace_id: str,
        agent_id: str,
        phone_number_id: str,
    ) -> Dict[str, Any]:
        logger.info(f"[CallSessionManager] Registering inbound call {call_uuid} for agent {agent_id}")
        context = {
            "call_uuid": call_uuid,
            "caller_id": caller_id,
            "dialed_number": dialed_number,
            "workspace_id": workspace_id,
            "agent_id": agent_id,
            "phone_number_id": phone_number_id,
            "provider": "asterisk",
            "direction": "inbound",
            "status": "created",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "started_at": None,
            "ended_at": None,
            "agent_config": {},
            "cost_cents": 0
        }
        self.active_calls[call_uuid] = context
        return context

    async def get_call_context(self, call_uuid: str) -> Optional[Dict[str, Any]]:
        context = self.active_calls.get(call_uuid)
        if not context:
            try:
                db = get_supabase_client()
                def _query():
                    return db.table("calls").select("*").eq("call_uuid", call_uuid).execute()
                res = await asyncio.to_thread(_query)
                if res.data:
                    row = res.data[0]
                    context = self.register_inbound_asterisk_call(
                        call_uuid=call_uuid,
                        caller_id=row.get("caller_id") or row.get("caller_phone_number") or "",
                        dialed_number=row.get("dialed_number") or "",
                        workspace_id=row.get("workspace_id"),
                        agent_id=row.get("agent_id"),
                        phone_number_id=row.get("phone_number_id"),
                    )
                    context["status"] = row.get("status")
            except Exception as e:
                logger.error(f"[CallSessionManager] DB recovery lookup failed for {call_uuid}: {e}")
                return None

        if context:
            if not context.get("agent_config"):
                try:
                    db = get_supabase_client()
                    agent_id = context["agent_id"]
                    agent = await asyncio.to_thread(fetch_agent_with_context, db, agent_id)
                    if agent:
                        kb_meta = agent.get("kb_metadata") or {}
                        context["agent_config"] = {
                            "name": agent.get("name"),
                            "model": agent.get("model"),
                            "language": agent.get("language") or "hi-IN",
                            "voice_id": agent.get("voice_id") or "aura-asteria-en",
                            "tts_provider": kb_meta.get("tts_provider") or "deepgram",
                            "agent_system_prompt": agent.get("agent_system_prompt") or "",
                            "system_prompt": agent.get("system_prompt") or "",
                            "knowledge_base": agent.get("knowledge_base") or "",
                            "voice_gender": kb_meta.get("voice_gender") or "female",
                            "voice_speed": agent.get("voice_speed"),
                        }
                        logger.info(f"[CallSessionManager] Loaded agent config for call {call_uuid}")
                except Exception as e:
                    logger.error(f"[CallSessionManager] Failed to load agent details for call {call_uuid}: {e}")
            return context
        return None

    def start_audio_session(self, call_uuid: str) -> bool:
        context = self.active_calls.get(call_uuid)
        if not context:
            return False
        context["status"] = "in_progress"
        context["started_at"] = datetime.now(timezone.utc).isoformat()
        logger.info(f"[CallSessionManager] Audio session started for {call_uuid}")

        db = get_supabase_client()
        def _update():
            try:
                db.table("calls").update({
                    "status": "in_progress",
                    "started_at": context["started_at"]
                }).eq("call_uuid", call_uuid).execute()
            except Exception as e:
                logger.error(f"[CallSessionManager] DB status update error for {call_uuid}: {e}")

        asyncio.create_task(asyncio.to_thread(_update))
        return True

    def end_call(self, call_uuid: str, reason: str = "hangup") -> bool:
        context = self.active_calls.get(call_uuid)
        if not context:
            return False
        context["status"] = "completed"
        context["ended_at"] = datetime.now(timezone.utc).isoformat()
        context["end_reason"] = reason

        duration = 0
        if context.get("started_at"):
            try:
                start_dt = datetime.fromisoformat(context["started_at"].replace("Z", "+00:00"))
                end_dt = datetime.fromisoformat(context["ended_at"].replace("Z", "+00:00"))
                duration = int((end_dt - start_dt).total_seconds())
            except Exception as e:
                logger.error(f"[CallSessionManager] Error calculating duration for {call_uuid}: {e}")

        context["duration_seconds"] = duration
        logger.info(f"[CallSessionManager] Call {call_uuid} ended. Reason: {reason}, Duration: {duration}s")

        db = get_supabase_client()
        def _update():
            try:
                db.table("calls").update({
                    "status": "completed",
                    "ended_at": context["ended_at"],
                    "duration_seconds": duration,
                    "actual_duration": duration
                }).eq("call_uuid", call_uuid).execute()
            except Exception as e:
                logger.error(f"[CallSessionManager] DB update error on end_call {call_uuid}: {e}")

        asyncio.create_task(asyncio.to_thread(_update))
        return True

    def register_cleanup_callback(self, call_uuid: str, callback: Callable[[str], None]) -> None:
        self.cleanup_callbacks[call_uuid] = callback

    def cleanup_call(self, call_uuid: str) -> None:
        logger.info(f"[CallSessionManager] Cleaning up call {call_uuid}")
        callback = self.cleanup_callbacks.pop(call_uuid, None)
        if callback:
            try:
                callback(call_uuid)
            except Exception as e:
                logger.error(f"[CallSessionManager] Error during cleanup callback for {call_uuid}: {e}")
        self.active_calls.pop(call_uuid, None)
        logger.info(f"[CallSessionManager] Cleaned up in-memory call context for {call_uuid}")

call_session_manager = CallSessionManager()
