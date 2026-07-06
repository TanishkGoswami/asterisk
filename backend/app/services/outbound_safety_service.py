import os
import re
import logging
from datetime import datetime, timezone
from typing import Optional, Tuple
from pydantic import BaseModel
from app.db.client import get_supabase_client
from app.core.config import settings

logger = logging.getLogger(__name__)

class DialSafetyResult(BaseModel):
    allowed: bool
    reason_code: str
    human_readable_reason: str
    safe_to_retry: bool
    should_pause_campaign: bool

def mask_phone_number(phone: str) -> str:
    """Masks phone number middle digits, leaving country prefix and last 2 digits."""
    if not phone:
        return ""
    phone_clean = phone.strip()
    if phone_clean.startswith("+"):
        if len(phone_clean) > 5:
            return f"{phone_clean[:3]}{'*' * (len(phone_clean) - 5)}{phone_clean[-2:]}"
    else:
        if len(phone_clean) > 4:
            return f"{phone_clean[:2]}{'*' * (len(phone_clean) - 4)}{phone_clean[-2:]}"
    return "***"

def get_kill_switch_enabled(env_name: str) -> bool:
    """Get kill switch value from process environment, falling back to settings."""
    val = os.environ.get(env_name)
    if val is not None:
        return val.strip().lower() in ("true", "1", "yes")

    value = getattr(settings, env_name, None)
    if value is None:
        return False
    return bool(value)

async def record_safety_event(
    db,
    workspace_id: Optional[str],
    agent_id: Optional[str],
    phone_number: str,
    call_uuid: Optional[str],
    event_type: str,
    reason_code: str,
    safe_to_retry: bool,
    should_pause_campaign: bool,
    dry_run: bool,
    batch_run_id: Optional[str] = None,
    batch_item_id: Optional[str] = None,
    worker_instance_id: Optional[str] = None,
    metadata_payload: Optional[dict] = None
) -> None:
    """Audit safety validation events into the outbound_safety_events table."""
    try:
        masked = mask_phone_number(phone_number)
        db.table("outbound_safety_events").insert({
            "workspace_id": workspace_id,
            "agent_id": agent_id,
            "call_uuid": call_uuid,
            "batch_run_id": batch_run_id,
            "batch_item_id": batch_item_id,
            "event_type": event_type,
            "masked_phone_number": masked,
            "reason_code": reason_code,
            "safe_to_retry": safe_to_retry,
            "should_pause_campaign": should_pause_campaign,
            "worker_instance_id": worker_instance_id,
            "dry_run": dry_run,
            "metadata": metadata_payload or {},
            "created_at": datetime.now(timezone.utc).isoformat()
        }).execute()
    except Exception as e:
        logger.warning(f"[Outbound Safety Audit] Failed to record safety event: {e}")

async def check_circuit_breaker(redis_client) -> Tuple[bool, str]:
    """Verify circuit breaker failure thresholds stored in Redis. Returns (is_tripped, reason)."""
    if not redis_client:
        return True, "Redis connection down (circuit breaker check failed)"
    try:
        if redis_client.get("circuit:manual_open"):
            return True, "Manual circuit breaker trip active"
            
        now = datetime.now(timezone.utc).timestamp()
        
        # 1. Asterisk originate failures (3 in 2 minutes)
        orig_fails = redis_client.lrange("circuit:orig_fails", 0, -1) or []
        orig_count = sum(1 for t in orig_fails if now - float(t) < 120)
        if orig_count >= 3:
            return True, f"Asterisk originate failures active: {orig_count} in last 2 mins"
            
        # 2. Trunk failures (3 in 2 minutes)
        trunk_fails = redis_client.lrange("circuit:trunk_fails", 0, -1) or []
        trunk_count = sum(1 for t in trunk_fails if now - float(t) < 120)
        if trunk_count >= 3:
            return True, f"Trunk failures active: {trunk_count} in last 2 mins"
            
        # 3. Preflight exceptions (5 in 5 minutes)
        pref_fails = redis_client.lrange("circuit:pref_fails", 0, -1) or []
        pref_count = sum(1 for t in pref_fails if now - float(t) < 300)
        if pref_count >= 5:
            return True, f"Preflight exceptions active: {pref_count} in last 5 mins"
            
        return False, ""
    except Exception as e:
        logger.warning(f"Error checking circuit breaker in Redis: {e}")
        return True, f"Circuit breaker error: {str(e)}"

def record_circuit_failure(fail_type: str):
    """Increment failure counters in Redis for circuit breaker tracking."""
    from app.services.call_admission_control import redis_client
    if not redis_client:
        return
    try:
        now = datetime.now(timezone.utc).timestamp()
        key_map = {
            "originate": "circuit:orig_fails",
            "trunk": "circuit:trunk_fails",
            "preflight": "circuit:pref_fails"
        }
        key = key_map.get(fail_type)
        if key:
            redis_client.rpush(key, str(now))
            redis_client.expire(key, 300)
    except Exception as e:
        logger.error(f"Failed to record circuit failure {fail_type}: {e}")

async def verify_outbound_dial_safety(
    workspace_id: str,
    agent_id: str,
    phone_number: str,
    call_uuid: str,
    batch_run_id: Optional[str] = None,
    batch_item_id: Optional[str] = None,
    dry_run: bool = False,
    worker_instance_id: Optional[str] = None
) -> DialSafetyResult:
    """Centralized safety preflight layer that enforces kill switches, status checks, and health before Twilio originate."""
    db = get_supabase_client()
    from app.services.call_admission_control import redis_client
    
    try:
        # Dry runs validate campaign inputs and database state, but skip live telephony gates.
        if not dry_run:
            # 1. Scope Kill Switches
            outbound_calls_enabled = get_kill_switch_enabled("OUTBOUND_CALLS_ENABLED")
            batch_calls_enabled = get_kill_switch_enabled("BATCH_CALLS_ENABLED")
            
            # All outbound calls must satisfy OUTBOUND_CALLS_ENABLED
            if not outbound_calls_enabled:
                res = DialSafetyResult(
                    allowed=False,
                    reason_code="outbound_calls_disabled",
                    human_readable_reason="All outbound calls are globally disabled by kill switch",
                    safe_to_retry=True,
                    should_pause_campaign=True
                )
                await record_safety_event(db, workspace_id, agent_id, phone_number, call_uuid, "dial_blocked", res.reason_code, res.safe_to_retry, res.should_pause_campaign, dry_run, batch_run_id, batch_item_id, worker_instance_id)
                return res
                
            # Batch campaigns require BATCH_CALLS_ENABLED
            if batch_run_id and not batch_calls_enabled:
                res = DialSafetyResult(
                    allowed=False,
                    reason_code="batch_calls_disabled",
                    human_readable_reason="Batch calling is globally disabled by kill switch",
                    safe_to_retry=True,
                    should_pause_campaign=True
                )
                await record_safety_event(db, workspace_id, agent_id, phone_number, call_uuid, "dial_blocked", res.reason_code, res.safe_to_retry, res.should_pause_campaign, dry_run, batch_run_id, batch_item_id, worker_instance_id)
                return res
                
            # Real dialing switches check
            real_dialing_enabled = get_kill_switch_enabled("REAL_DIALING_ENABLED")
            twilio_sip_trunk_enabled = get_kill_switch_enabled("TWILIO_SIP_TRUNK_ENABLED")
            
            if not real_dialing_enabled:
                res = DialSafetyResult(
                    allowed=False,
                    reason_code="real_dialing_disabled",
                    human_readable_reason="Real dialing is disabled by kill switch",
                    safe_to_retry=True,
                    should_pause_campaign=True
                )
                await record_safety_event(db, workspace_id, agent_id, phone_number, call_uuid, "dial_blocked", res.reason_code, res.safe_to_retry, res.should_pause_campaign, dry_run, batch_run_id, batch_item_id, worker_instance_id)
                return res
            if not twilio_sip_trunk_enabled:
                res = DialSafetyResult(
                    allowed=False,
                    reason_code="twilio_sip_trunk_disabled",
                    human_readable_reason="Twilio SIP trunk dialing is disabled by kill switch",
                    safe_to_retry=True,
                    should_pause_campaign=True
                )
                await record_safety_event(db, workspace_id, agent_id, phone_number, call_uuid, "dial_blocked", res.reason_code, res.safe_to_retry, res.should_pause_campaign, dry_run, batch_run_id, batch_item_id, worker_instance_id)
                return res

            # 2. Redis Connection & Circuit Breaker Checks (unless bypassed)
            if not settings.allow_calls_without_redis:
                if not redis_client:
                    res = DialSafetyResult(
                        allowed=False,
                        reason_code="redis_unavailable",
                        human_readable_reason="Redis cache is unreachable (fail-closed)",
                        safe_to_retry=True,
                        should_pause_campaign=True
                    )
                    await record_safety_event(db, workspace_id, agent_id, phone_number, call_uuid, "dial_blocked", res.reason_code, res.safe_to_retry, res.should_pause_campaign, dry_run, batch_run_id, batch_item_id, worker_instance_id)
                    return res
                try:
                    redis_client.ping()
                except Exception as redis_err:
                    res = DialSafetyResult(
                        allowed=False,
                        reason_code="redis_unavailable",
                        human_readable_reason=f"Redis is unreachable: {redis_err}",
                        safe_to_retry=True,
                        should_pause_campaign=True
                    )
                    await record_safety_event(db, workspace_id, agent_id, phone_number, call_uuid, "dial_blocked", res.reason_code, res.safe_to_retry, res.should_pause_campaign, dry_run, batch_run_id, batch_item_id, worker_instance_id)
                    return res

                # 3. Circuit Breaker Check
                is_tripped, cb_reason = await check_circuit_breaker(redis_client)
                if is_tripped:
                    res = DialSafetyResult(
                        allowed=False,
                        reason_code="circuit_breaker_open",
                        human_readable_reason=f"Circuit breaker is OPEN: {cb_reason}",
                        safe_to_retry=False,
                        should_pause_campaign=True
                    )
                    await record_safety_event(db, workspace_id, agent_id, phone_number, call_uuid, "dial_blocked", res.reason_code, res.safe_to_retry, res.should_pause_campaign, dry_run, batch_run_id, batch_item_id, worker_instance_id)
                    return res

        # 4. Destination Phone Format Validation
        phone_clean = phone_number.strip()
        if not phone_clean or not re.match(r"^\+[1-9]\d{1,14}$", phone_clean):
            res = DialSafetyResult(
                allowed=False,
                reason_code="invalid_number",
                human_readable_reason=f"Phone number '{phone_clean}' is not valid E.164 format",
                safe_to_retry=False,
                should_pause_campaign=False
            )
            await record_safety_event(db, workspace_id, agent_id, phone_number, call_uuid, "dial_blocked", res.reason_code, res.safe_to_retry, res.should_pause_campaign, dry_run, batch_run_id, batch_item_id, worker_instance_id)
            return res

        # 5. Workspace Active Status Verification
        ws_res = db.table("workspaces").select("status").eq("id", workspace_id).execute()
        if not ws_res.data:
            res = DialSafetyResult(
                allowed=False,
                reason_code="workspace_not_found",
                human_readable_reason="Workspace not found in database",
                safe_to_retry=False,
                should_pause_campaign=True
            )
            await record_safety_event(db, workspace_id, agent_id, phone_number, call_uuid, "dial_blocked", res.reason_code, res.safe_to_retry, res.should_pause_campaign, dry_run, batch_run_id, batch_item_id, worker_instance_id)
            return res
        ws = ws_res.data[0]
        if ws.get("status") == "suspended":
            res = DialSafetyResult(
                allowed=False,
                reason_code="workspace_suspended",
                human_readable_reason="Workspace is currently suspended",
                safe_to_retry=False,
                should_pause_campaign=True
            )
            await record_safety_event(db, workspace_id, agent_id, phone_number, call_uuid, "dial_blocked", res.reason_code, res.safe_to_retry, res.should_pause_campaign, dry_run, batch_run_id, batch_item_id, worker_instance_id)
            return res

        # Check outbound_enabled on workspace_limits table (defaults to True if row missing)
        outbound_enabled = True
        limits_res = db.table("workspace_limits").select("outbound_enabled").eq("workspace_id", workspace_id).execute()
        if limits_res.data:
            outbound_enabled = limits_res.data[0].get("outbound_enabled", True)

        if not outbound_enabled:
            res = DialSafetyResult(
                allowed=False,
                reason_code="outbound_disabled",
                human_readable_reason="Outbound calling is disabled for this workspace",
                safe_to_retry=False,
                should_pause_campaign=True
            )
            await record_safety_event(db, workspace_id, agent_id, phone_number, call_uuid, "dial_blocked", res.reason_code, res.safe_to_retry, res.should_pause_campaign, dry_run, batch_run_id, batch_item_id, worker_instance_id)
            return res

        # 6. Agent Active Status Verification
        agent_res = db.table("agents").select("id, status").eq("id", agent_id).eq("workspace_id", workspace_id).execute()
        if not agent_res.data:
            res = DialSafetyResult(
                allowed=False,
                reason_code="agent_not_found",
                human_readable_reason="Agent not found in workspace",
                safe_to_retry=False,
                should_pause_campaign=False
            )
            await record_safety_event(db, workspace_id, agent_id, phone_number, call_uuid, "dial_blocked", res.reason_code, res.safe_to_retry, res.should_pause_campaign, dry_run, batch_run_id, batch_item_id, worker_instance_id)
            return res
        agent = agent_res.data[0]
        if agent.get("status") == "inactive":
            res = DialSafetyResult(
                allowed=False,
                reason_code="agent_inactive",
                human_readable_reason="Agent is currently marked inactive",
                safe_to_retry=False,
                should_pause_campaign=False
            )
            await record_safety_event(db, workspace_id, agent_id, phone_number, call_uuid, "dial_blocked", res.reason_code, res.safe_to_retry, res.should_pause_campaign, dry_run, batch_run_id, batch_item_id, worker_instance_id)
            return res

        # 7. SIP Outbound Trunk Verification
        trunks_res = db.table("sip_trunk_providers").select("id, status, provider_type").eq("workspace_id", workspace_id).execute()
        if not trunks_res.data:
            res = DialSafetyResult(
                allowed=False,
                reason_code="invalid_trunk_config",
                human_readable_reason="No SIP Trunk provider configured for this workspace",
                safe_to_retry=False,
                should_pause_campaign=True
            )
            await record_safety_event(db, workspace_id, agent_id, phone_number, call_uuid, "dial_blocked", res.reason_code, res.safe_to_retry, res.should_pause_campaign, dry_run, batch_run_id, batch_item_id, worker_instance_id)
            return res
        trunk = trunks_res.data[0]
        if trunk.get("status") == "disabled":
            res = DialSafetyResult(
                allowed=False,
                reason_code="invalid_trunk_config",
                human_readable_reason="SIP Trunk provider is disabled",
                safe_to_retry=False,
                should_pause_campaign=True
            )
            await record_safety_event(db, workspace_id, agent_id, phone_number, call_uuid, "dial_blocked", res.reason_code, res.safe_to_retry, res.should_pause_campaign, dry_run, batch_run_id, batch_item_id, worker_instance_id)
            return res

            # 8. Asterisk Process Status Verification (if local mode, verify AudioSocket port is listening)
            if settings.asterisk_mode == "local":
                import socket
                audiosocket_listening = False
                try:
                    with socket.create_connection(("127.0.0.1", 9092), timeout=1.0):
                        audiosocket_listening = True
                except Exception:
                    pass
                if not audiosocket_listening:
                    res = DialSafetyResult(
                        allowed=False,
                        reason_code="asterisk_unavailable",
                        human_readable_reason="Local AudioSocket listener is not active on port 9092",
                        safe_to_retry=True,
                        should_pause_campaign=True
                    )
                    await record_safety_event(db, workspace_id, agent_id, phone_number, call_uuid, "dial_blocked", res.reason_code, res.safe_to_retry, res.should_pause_campaign, dry_run, batch_run_id, batch_item_id, worker_instance_id)
                    return res

        # 9. Campaign status checks (if batch campaign context is supplied)
        if batch_run_id:
            run_res = db.table("batch_call_runs").select("status").eq("id", batch_run_id).execute()
            if not run_res.data:
                res = DialSafetyResult(
                    allowed=False,
                    reason_code="campaign_not_found",
                    human_readable_reason="Campaign run not found in database",
                    safe_to_retry=False,
                    should_pause_campaign=True
                )
                await record_safety_event(db, workspace_id, agent_id, phone_number, call_uuid, "dial_blocked", res.reason_code, res.safe_to_retry, res.should_pause_campaign, dry_run, batch_run_id, batch_item_id, worker_instance_id)
                return res
            run_status = run_res.data[0]["status"]
            if run_status != "running":
                res = DialSafetyResult(
                    allowed=False,
                    reason_code="campaign_not_running",
                    human_readable_reason=f"Campaign run is not active (current status: {run_status})",
                    safe_to_retry=False,
                    should_pause_campaign=True
                )
                await record_safety_event(db, workspace_id, agent_id, phone_number, call_uuid, "dial_blocked", res.reason_code, res.safe_to_retry, res.should_pause_campaign, dry_run, batch_run_id, batch_item_id, worker_instance_id)
                return res

        # Safety verified successfully!
        return DialSafetyResult(
            allowed=True,
            reason_code="allowed",
            human_readable_reason="All preflight safety checks passed",
            safe_to_retry=True,
            should_pause_campaign=False
        )

    except Exception as e:
        record_circuit_failure("preflight")
        logger.error(f"[Outbound Safety Preflight Exception] Fail-closed: {e}", exc_info=True)
        await record_safety_event(
            db=db,
            workspace_id=workspace_id,
            agent_id=agent_id,
            phone_number=phone_number,
            call_uuid=call_uuid,
            event_type="blocked_exception",
            reason_code="safety_preflight_exception",
            safe_to_retry=True,
            should_pause_campaign=True,
            dry_run=dry_run,
            batch_run_id=batch_run_id,
            batch_item_id=batch_item_id,
            worker_instance_id=worker_instance_id,
            metadata_payload={"error": str(e)}
        )
        return DialSafetyResult(
            allowed=False,
            reason_code="safety_preflight_exception",
            human_readable_reason=f"Safety preflight verification threw exception: {e}",
            safe_to_retry=True,
            should_pause_campaign=True
        )
