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
            # Still attempt to release from Redis even if context was cleaned up
            try:
                from app.services.call_admission_control import release_call_reservation
                release_call_reservation(call_uuid)
            except Exception:
                pass
            return False

        # Release Redis slot
        try:
            from app.services.call_admission_control import release_call_reservation
            release_call_reservation(call_uuid)
        except Exception as e:
            logger.error(f"[CallSessionManager] Failed to release call reservation: {e}")

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
        
        # Calculate estimated cost if cost_calculator is present (or default to 0.0)
        cost_data = None
        estimated_cost = 0.0
        try:
            from app.services.cost_calculator import calculate_provider_costs
            from app.core.config import settings
            cost_data = calculate_provider_costs(
                duration_seconds=duration,
                stt_provider="deepgram",
                tts_provider=context.get("agent_config", {}).get("tts_provider") or "deepgram",
                tts_characters=duration * 3, # Estimate 3 chars per second
                llm_model=context.get("agent_config", {}).get("model") or "gpt-4-turbo",
                llm_input_tokens=duration * 4, # Estimate 4 tokens per second input
                llm_output_tokens=duration * 2, # Estimate 2 tokens per second output
                usd_to_inr=settings.usd_to_inr,
                credit_value_inr=settings.credit_value_inr
            )
            estimated_cost = float(cost_data.get("credits_used") or 0.0)
        except Exception as calc_err:
            logger.warning(f"Could not calculate call usage cost: {calc_err}")

        def _update():
            try:
                # Update call row in DB
                db.table("calls").update({
                    "status": "completed",
                    "ended_at": context["ended_at"],
                    "duration_seconds": duration,
                    "actual_duration": duration,
                    "hangup_reason": reason,
                    "estimated_cost": estimated_cost
                }).eq("call_uuid", call_uuid).execute()

                # Save cost breakdown in call_usage table
                if cost_data:
                    cost_data["call_id"] = call_uuid
                    cost_data["cost_status"] = "final"
                    cost_data["cost_finalized_at"] = datetime.now(timezone.utc).isoformat()
                    db.table("call_usage").upsert(cost_data, on_conflict="call_id").execute()

                # Update workspace monthly usage counter
                workspace_id = context.get("workspace_id")
                if workspace_id and duration > 0:
                    current_month = datetime.now(timezone.utc).strftime("%Y-%m")
                    used_seconds = duration
                    used_minutes = round(duration / 60.0, 4)

                    # Fetch current monthly usage row
                    usage_res = db.table("workspace_usage_counters").select("*").eq("workspace_id", workspace_id).eq("billing_month", current_month).execute()
                    if usage_res.data:
                        row = usage_res.data[0]
                        new_seconds = int(row.get("used_seconds") or 0) + used_seconds
                        new_minutes = float(row.get("used_minutes") or 0.0) + used_minutes
                        new_cost = float(row.get("estimated_cost") or 0.0) + estimated_cost
                        db.table("workspace_usage_counters").update({
                            "used_seconds": new_seconds,
                            "used_minutes": new_minutes,
                            "estimated_cost": new_cost,
                            "updated_at": datetime.now(timezone.utc).isoformat()
                        }).eq("id", row["id"]).execute()
                    else:
                        db.table("workspace_usage_counters").insert({
                            "workspace_id": workspace_id,
                            "billing_month": current_month,
                            "used_seconds": used_seconds,
                            "used_minutes": used_minutes,
                            "estimated_cost": estimated_cost,
                            "updated_at": datetime.now(timezone.utc).isoformat()
                        }).execute()
                    logger.info(f"[CallSessionManager] Updated monthly usage counter for workspace {workspace_id}")
            except Exception as e:
                logger.error(f"[CallSessionManager] DB update error on end_call {call_uuid}: {e}")

        asyncio.create_task(asyncio.to_thread(_update))
        return True

    def register_cleanup_callback(self, call_uuid: str, callback: Callable[[str], None]) -> None:
        existing = self.cleanup_callbacks.get(call_uuid)
        if existing:
            def chained_callback(uuid):
                try:
                    existing(uuid)
                except Exception as e:
                    logger.error(f"[CallSessionManager] Error in existing callback for {uuid}: {e}")
                try:
                    callback(uuid)
                except Exception as e:
                    logger.error(f"[CallSessionManager] Error in chained callback for {uuid}: {e}")
            self.cleanup_callbacks[call_uuid] = chained_callback
            logger.info(f"[CallSessionManager] Chained new cleanup callback for call {call_uuid}")
        else:
            self.cleanup_callbacks[call_uuid] = callback
            logger.info(f"[CallSessionManager] Registered cleanup callback for call {call_uuid}")

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

    def cleanup_stale_calls(self, timeout_seconds: int = 120) -> None:
        """Finds calls in 'created' status that have exceeded the timeout, and cleans them up."""
        now = datetime.now(timezone.utc)
        stale_uuids = []
        for call_uuid, context in list(self.active_calls.items()):
            if context.get("status") == "created":
                created_at_str = context.get("created_at")
                if created_at_str:
                    try:
                        # Handle potential timezone offsets
                        created_at = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
                        elapsed = (now - created_at).total_seconds()
                        if elapsed > timeout_seconds:
                            stale_uuids.append(call_uuid)
                    except Exception as e:
                        logger.error(f"[CallSessionManager] Error parsing created_at for {call_uuid}: {e}")
        
        for call_uuid in stale_uuids:
            logger.warning(f"[CallSessionManager] Call {call_uuid} was registered but never connected to AudioSocket. Cleaning up as stale (no answer).")
            # We treat this as a no_answer/failed call
            self.end_call(call_uuid, "NOANSWER")
            self.cleanup_call(call_uuid)

call_session_manager = CallSessionManager()
