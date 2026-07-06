import logging
import json
import redis
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple, Dict, Any
from app.core.config import settings
from app.db.client import get_supabase_client, Client

logger = logging.getLogger(__name__)

# Initialize Redis client
try:
    redis_client = redis.from_url(settings.redis_url, decode_responses=True)
except Exception as e:
    logger.critical(f"[CAC] Failed to initialize Redis connection: {e}")
    redis_client = None

# Lua Script for atomic increment and limit check
RESERVE_LUA = """
local ws_key = KEYS[1]
local agent_key = KEYS[2]
local trunk_key = KEYS[3]

local ws_limit = tonumber(ARGV[1])
local agent_limit = tonumber(ARGV[2])
local trunk_limit = tonumber(ARGV[3])

-- Check current counts
local ws_count = tonumber(redis.call('GET', ws_key) or "0")
local agent_count = tonumber(redis.call('GET', agent_key) or "0")
local trunk_count = tonumber(redis.call('GET', trunk_key) or "0")

-- Validate workspace concurrent limits
if ws_limit >= 0 and ws_count >= ws_limit then
    return {0, "workspace_concurrency_limit"}
end

-- Validate agent concurrent limits (if configured)
if agent_limit >= 0 and agent_count >= agent_limit then
    return {0, "agent_concurrency_limit"}
end

-- Validate trunk concurrent limits (if configured)
if trunk_limit >= 0 and trunk_count >= trunk_limit then
    return {0, "sip_trunk_concurrency_limit"}
end

-- Atomically increment active counts
redis.call('INCR', ws_key)
local inc_agent = 0
if agent_limit >= 0 then
    redis.call('INCR', agent_key)
    inc_agent = 1
end
local inc_trunk = 0
if trunk_limit >= 0 then
    redis.call('INCR', trunk_key)
    inc_trunk = 1
end

return {1, tostring(inc_agent) .. ":" .. tostring(inc_trunk)}
"""

RELEASE_LUA = """
local ws_key = KEYS[1]
local agent_key = KEYS[2]
local trunk_key = KEYS[3]

local decr_ws = tonumber(ARGV[1])
local decr_agent = tonumber(ARGV[2])
local decr_trunk = tonumber(ARGV[3])

-- Safely decrement workspace active calls
if decr_ws == 1 then
    local ws_count = tonumber(redis.call('GET', ws_key) or "0")
    if ws_count > 0 then
        redis.call('DECR', ws_key)
    end
end

-- Safely decrement agent active calls
if decr_agent == 1 then
    local agent_count = tonumber(redis.call('GET', agent_key) or "0")
    if agent_count > 0 then
        redis.call('DECR', agent_key)
    end
end

-- Safely decrement trunk active calls
if decr_trunk == 1 then
    local trunk_count = tonumber(redis.call('GET', trunk_key) or "0")
    if trunk_count > 0 then
        redis.call('DECR', trunk_key)
    end
end

return 1
"""


def log_call_limit_event(
    workspace_id: Optional[str],
    agent_id: Optional[str],
    sip_trunk_provider_id: Optional[str],
    did_number_id: Optional[str],
    call_uuid: Optional[str],
    direction: str,
    reason: str,
    caller_id: Optional[str] = None,
    dialed_number: Optional[str] = None,
    destination_number: Optional[str] = None,
    metadata: Optional[dict] = None
):
    """Log rejected call details to database for audit and dashboard display."""
    try:
        db = get_supabase_client()
        db.table("call_limit_events").insert({
            "workspace_id": workspace_id,
            "agent_id": agent_id,
            "sip_trunk_provider_id": sip_trunk_provider_id,
            "did_number_id": did_number_id,
            "call_uuid": call_uuid,
            "direction": direction,
            "reason": reason,
            "caller_id": caller_id,
            "dialed_number": dialed_number,
            "destination_number": destination_number,
            "metadata": metadata or {}
        }).execute()
        logger.info(f"[CAC] Limit event logged for call_uuid={call_uuid}, reason={reason}")
    except Exception as db_err:
        logger.error(f"[CAC] Failed to log call limit event in Supabase: {db_err}")


async def check_and_reserve_call(
    call_uuid: str,
    direction: str,
    workspace_id: str,
    agent_id: str,
    sip_trunk_provider_id: Optional[str] = None,
    did_number_id: Optional[str] = None,
    caller_id: Optional[str] = None,
    dialed_number: Optional[str] = None,
    destination_number: Optional[str] = None,
) -> Tuple[bool, Optional[str]]:
    """
    Perform call admission checks and reserve a call slot atomically in Redis.
    Checks:
    - Workspace exists & is active (not suspended/overdue)
    - Direction is enabled
    - Monthly minutes limits
    - Concurrency caps (Workspace, Agent, and SIP Trunk)
    - Agent & SIP Trunk statuses
    """
    logger.info(f"[CAC] Starting checks for {direction} call {call_uuid} in workspace {workspace_id}")

    try:
        db = get_supabase_client()

        # 1. Fetch Workspace limits/status
        limits_res = await asyncio.to_thread(
            db.table("workspace_limits").select("*").eq("workspace_id", workspace_id).execute
        )
        
        limits = {}
        if limits_res.data:
            limits = limits_res.data[0]
        else:
            # Load default limits from workspaces table
            ws_res = await asyncio.to_thread(
                db.table("workspaces").select("status, call_limit, concurrent_call_limit").eq("id", workspace_id).execute
            )
            if not ws_res.data:
                log_call_limit_event(workspace_id, agent_id, sip_trunk_provider_id, did_number_id, call_uuid, direction, "workspace_not_found", caller_id, dialed_number, destination_number)
                return False, "workspace_not_found"
            
            ws_data = ws_res.data[0]
            limits = {
                "monthly_minute_limit": ws_data.get("call_limit") or 1000,
                "max_concurrent_calls": ws_data.get("concurrent_call_limit") or settings.default_workspace_max_concurrent_calls or 1,
                "billing_status": "active" if ws_data.get("status") == "active" else "suspended",
                "inbound_enabled": True,
                "outbound_enabled": True
            }

        # Validate billing status
        billing_status = limits.get("billing_status") or "active"
        if billing_status == "suspended":
            log_call_limit_event(workspace_id, agent_id, sip_trunk_provider_id, did_number_id, call_uuid, direction, "workspace_suspended", caller_id, dialed_number, destination_number)
            return False, "workspace_suspended"
        
        if settings.block_overdue_workspaces and billing_status == "overdue":
            log_call_limit_event(workspace_id, agent_id, sip_trunk_provider_id, did_number_id, call_uuid, direction, "billing_overdue", caller_id, dialed_number, destination_number)
            return False, "billing_overdue"

        # Validate direction flags
        if direction == "inbound" and not limits.get("inbound_enabled", True):
            log_call_limit_event(workspace_id, agent_id, sip_trunk_provider_id, did_number_id, call_uuid, direction, "inbound_disabled", caller_id, dialed_number, destination_number)
            return False, "inbound_disabled"
        if direction == "outbound" and not limits.get("outbound_enabled", True):
            log_call_limit_event(workspace_id, agent_id, sip_trunk_provider_id, did_number_id, call_uuid, direction, "outbound_disabled", caller_id, dialed_number, destination_number)
            return False, "outbound_disabled"

        # Validate monthly minute limit
        monthly_limit = limits.get("monthly_minute_limit")
        if monthly_limit is not None and monthly_limit > 0:
            try:
                current_month = datetime.now(timezone.utc).strftime("%Y-%m")
                usage_res = await asyncio.to_thread(
                    db.table("workspace_usage_counters").select("used_minutes").eq("workspace_id", workspace_id).eq("billing_month", current_month).execute
                )
                used_minutes = 0.0
                if usage_res.data:
                    used_minutes = float(usage_res.data[0].get("used_minutes") or 0.0)
                
                if used_minutes >= monthly_limit:
                    log_call_limit_event(workspace_id, agent_id, sip_trunk_provider_id, did_number_id, call_uuid, direction, "monthly_minutes_exhausted", caller_id, dialed_number, destination_number)
                    return False, "monthly_minutes_exhausted"
            except Exception as usage_err:
                # Table may not exist yet (migration pending) — treat as 0 usage, allow call
                logger.warning(f"[CAC] Could not query workspace_usage_counters (migration pending?): {usage_err}. Treating as 0 usage.")

        # 2. Validate Agent
        try:
            agent_res = await asyncio.to_thread(
                db.table("agents").select("status, max_concurrent_calls").eq("id", agent_id).execute
            )
        except Exception:
            # max_concurrent_calls column may not exist yet (migration pending)
            agent_res = await asyncio.to_thread(
                db.table("agents").select("status").eq("id", agent_id).execute
            )
        if not agent_res.data:
            log_call_limit_event(workspace_id, agent_id, sip_trunk_provider_id, did_number_id, call_uuid, direction, "agent_not_found", caller_id, dialed_number, destination_number)
            return False, "agent_not_found"
        
        agent_data = agent_res.data[0]
        if agent_data.get("status") != "active":
            log_call_limit_event(workspace_id, agent_id, sip_trunk_provider_id, did_number_id, call_uuid, direction, "agent_inactive", caller_id, dialed_number, destination_number)
            return False, "agent_inactive"

        agent_concurrency_cap = agent_data.get("max_concurrent_calls") or -1  # -1 = no limit

        # 3. Validate SIP Trunk (if attached)
        trunk_concurrency_cap = -1
        if sip_trunk_provider_id:
            try:
                trunk_res = await asyncio.to_thread(
                    db.table("sip_trunk_providers").select("status, max_concurrent_calls").eq("id", sip_trunk_provider_id).execute
                )
            except Exception:
                # max_concurrent_calls may not exist yet (migration pending)
                trunk_res = await asyncio.to_thread(
                    db.table("sip_trunk_providers").select("status").eq("id", sip_trunk_provider_id).execute
                )
            if not trunk_res.data:
                log_call_limit_event(workspace_id, agent_id, sip_trunk_provider_id, did_number_id, call_uuid, direction, "trunk_not_found", caller_id, dialed_number, destination_number)
                return False, "trunk_not_found"
            
            trunk_data = trunk_res.data[0]
            if trunk_data.get("status") not in ("active", "pending"):
                log_call_limit_event(workspace_id, agent_id, sip_trunk_provider_id, did_number_id, call_uuid, direction, "trunk_inactive", caller_id, dialed_number, destination_number)
                return False, "trunk_inactive"
            
            trunk_concurrency_cap = trunk_data.get("max_concurrent_calls") or -1

        if not redis_client:
            logger.critical("[CAC] Redis is offline. Performing fallback check.")
            if settings.allow_calls_without_redis:
                logger.warning(f"[CAC] Redis Offline - {direction.capitalize()} call allowed due to ALLOW_CALLS_WITHOUT_REDIS=True")
                return True, None
            else:
                log_call_limit_event(workspace_id, agent_id, sip_trunk_provider_id, did_number_id, call_uuid, direction, "internal_error", caller_id, dialed_number, destination_number, {"detail": "Redis Offline"})
                return False, "internal_error"

        # Call Lua script to verify concurrency caps and increment counters atomically
        ws_key = f"workspace:{workspace_id}:active_calls"
        agent_key = f"agent:{agent_id}:active_calls"
        trunk_key = f"trunk:{sip_trunk_provider_id or 'none'}:active_calls"

        ws_concurrency_cap = limits.get("max_concurrent_calls") or settings.default_workspace_max_concurrent_calls or 1

        try:
            # Register Lua script
            reserve_script = redis_client.register_script(RESERVE_LUA)
            success, result_detail = reserve_script(
                keys=[ws_key, agent_key, trunk_key],
                args=[ws_concurrency_cap, agent_concurrency_cap, trunk_concurrency_cap]
            )

            if success == 0:
                logger.warning(f"[CAC] Call reservation rejected atomically: {result_detail}")
                log_call_limit_event(workspace_id, agent_id, sip_trunk_provider_id, did_number_id, call_uuid, direction, result_detail, caller_id, dialed_number, destination_number)
                return False, result_detail

            # Succeeded! Parse which counters were incremented
            parts = result_detail.split(":")
            inc_agent = int(parts[0]) == 1
            inc_trunk = int(parts[1]) == 1

            # Store reservation record in Redis
            reservation_record = {
                "call_uuid": call_uuid,
                "direction": direction,
                "workspace_id": workspace_id,
                "agent_id": agent_id,
                "sip_trunk_provider_id": sip_trunk_provider_id,
                "did_number_id": did_number_id,
                "incremented": {
                    "workspace": True,
                    "agent": inc_agent,
                    "trunk": inc_trunk
                },
                "status": "reserved"
            }
            ttl = settings.call_reservation_ttl_seconds or 2700  # Default 45 mins
            redis_client.set(f"call:{call_uuid}:reservation", json.dumps(reservation_record), ex=ttl)
            
            # Store reservation in DB persistently
            expires_at = (datetime.now(timezone.utc) + timedelta(seconds=ttl)).isoformat()
            try:
                db.table("call_reservations").insert({
                    "call_uuid": call_uuid,
                    "direction": direction,
                    "workspace_id": workspace_id,
                    "agent_id": agent_id,
                    "sip_trunk_provider_id": sip_trunk_provider_id,
                    "did_number_id": did_number_id,
                    "status": "reserved",
                    "expires_at": expires_at,
                    "metadata": {
                        "incremented": {
                            "workspace": True,
                            "agent": inc_agent,
                            "trunk": inc_trunk
                        }
                    }
                }).execute()
            except Exception as db_err:
                logger.error(f"[CAC] Failed to insert call reservation record in DB: {db_err}")

            logger.info(f"[CAC] Call reservation succeeded for {call_uuid}")
            return True, None

        except Exception as redis_err:
            logger.error(f"[CAC] Redis transaction error: {redis_err}")
            if settings.allow_calls_without_redis:
                logger.warning(f"[CAC] Redis unavailable - {direction.capitalize()} call allowed due to ALLOW_CALLS_WITHOUT_REDIS=True")
                return True, None
            else:
                log_call_limit_event(workspace_id, agent_id, sip_trunk_provider_id, did_number_id, call_uuid, direction, "internal_error", caller_id, dialed_number, destination_number, {"detail": "Redis transaction failed"})
                return False, "internal_error"



    except Exception as e:
        logger.error(f"[CAC] Unexpected error during admission control: {e}", exc_info=True)
        return False, "internal_error"


def release_call_reservation(call_uuid: str) -> bool:
    """
    Idempotently release the concurrent call slots reserved in Redis for a call session.
    Guards against negative counters by decrementing only if previously reserved/incremented.
    """
    db = get_supabase_client()
    now_iso = datetime.now(timezone.utc).isoformat()
    
    # Idempotency lock via database first
    db_updated = False
    try:
        # Atomic database update to mark as released only if currently reserved
        db_res = db.table("call_reservations").update({
            "status": "released",
            "released_at": now_iso
        }).eq("call_uuid", call_uuid).eq("status", "reserved").execute()
        
        if db_res.data:
            db_updated = True
    except Exception as db_err:
        logger.error(f"[CAC] Failed to update call_reservations status to released in DB: {db_err}")

    if not redis_client:
        logger.warning("[CAC] Redis offline. Idempotent call reservation released in DB only.")
        return db_updated

    res_key = f"call:{call_uuid}:reservation"
    try:
        r_data = redis_client.get(res_key)
        if not r_data:
            logger.info(f"[CAC] Call release skipped for {call_uuid} in Redis: reservation not found or already released")
            return db_updated

        reservation = json.loads(r_data)
        if reservation.get("status") == "released":
            logger.info(f"[CAC] Call release skipped for {call_uuid} in Redis: already marked as released")
            return False

        workspace_id = reservation.get("workspace_id")
        agent_id = reservation.get("agent_id")
        sip_trunk_provider_id = reservation.get("sip_trunk_provider_id")
        incremented = reservation.get("incremented") or {}

        ws_key = f"workspace:{workspace_id}:active_calls"
        agent_key = f"agent:{agent_id}:active_calls"
        trunk_key = f"trunk:{sip_trunk_provider_id or 'none'}:active_calls"

        decr_ws = 1 if incremented.get("workspace") else 0
        decr_agent = 1 if incremented.get("agent") else 0
        decr_trunk = 1 if incremented.get("trunk") else 0

        # Execute Lua release script
        release_script = redis_client.register_script(RELEASE_LUA)
        release_script(
            keys=[ws_key, agent_key, trunk_key],
            args=[decr_ws, decr_agent, decr_trunk]
        )

        # Mark reservation as released in Redis (keep for 60s for idempotency history)
        reservation["status"] = "released"
        redis_client.set(res_key, json.dumps(reservation), ex=60)
        logger.info(f"[CAC] Call reservation released successfully for {call_uuid}")
        return True

    except Exception as e:
        logger.error(f"[CAC] Failed to release call reservation {call_uuid}: {e}")
        return False


def force_release_call_reservation(call_uuid: str) -> bool:
    """Administratively force-deletes a call reservation key and decrements counters."""
    return release_call_reservation(call_uuid)


async def run_live_call_monitor(call_uuid: str, session_hangup_fn) -> None:
    """
    Background loop that monitors call duration and limits.
    If workspace monthly minutes are exhausted, or status becomes suspended,
    it triggers session_hangup_fn.
    """
    interval = settings.call_usage_monitor_interval_seconds or 15
    logger.info(f"[CAC Monitor] Starting monitor loop for call {call_uuid} (interval={interval}s)")

    try:
        while True:
            await asyncio.sleep(interval)
            
            if not redis_client:
                continue

            # Read reservation details
            res_key = f"call:{call_uuid}:reservation"
            r_data = redis_client.get(res_key)
            if not r_data:
                logger.debug(f"[CAC Monitor] No reservation key found for {call_uuid}. Terminating monitor.")
                break

            reservation = json.loads(r_data)
            workspace_id = reservation.get("workspace_id")
            if not workspace_id:
                break

            try:
                db = get_supabase_client()
                limits_res = await asyncio.to_thread(
                    db.table("workspace_limits").select("monthly_minute_limit, billing_status").eq("workspace_id", workspace_id).execute
                )

                if not limits_res.data:
                    continue

                limits = limits_res.data[0]
                billing_status = limits.get("billing_status")
                monthly_limit = limits.get("monthly_minute_limit")

                # Workspace suspended mid-call
                if billing_status == "suspended":
                    logger.warning(f"[CAC Monitor] Workspace {workspace_id} suspended mid-call. Ending call {call_uuid}")
                    await session_hangup_fn("workspace_suspended")
                    break

                # Workspace limits minute checks
                if monthly_limit is not None and monthly_limit > 0:
                    current_month = datetime.now(timezone.utc).strftime("%Y-%m")
                    usage_res = await asyncio.to_thread(
                        db.table("workspace_usage_counters").select("used_minutes").eq("workspace_id", workspace_id).eq("billing_month", current_month).execute
                    )
                    used_minutes = 0.0
                    if usage_res.data:
                        used_minutes = float(usage_res.data[0].get("used_minutes") or 0.0)

                    if used_minutes >= monthly_limit:
                        logger.warning(f"[CAC Monitor] Workspace {workspace_id} minute limit reached ({used_minutes}/{monthly_limit}). Ending call {call_uuid}")
                        await session_hangup_fn("monthly_minutes_exhausted")
                        break
            except Exception as e:
                logger.error(f"[CAC Monitor] Error in checking limits for call {call_uuid}: {e}")

    except asyncio.CancelledError:
        logger.debug(f"[CAC Monitor] Live call monitor task cancelled for call {call_uuid}")


def get_active_reservations(workspace_id: Optional[str] = None) -> list:
    """Retrieve all active call reservations, filtering by workspace_id if provided."""
    if not redis_client:
        return []
    
    reservations = []
    # Scan call reservation keys
    for key in redis_client.scan_iter("call:*:reservation"):
        try:
            data = redis_client.get(key)
            if data:
                res = json.loads(data)
                if res.get("status") == "released":
                    continue
                if workspace_id and res.get("workspace_id") != workspace_id:
                    continue
                res["key"] = key
                res["call_uuid"] = key.split(":")[1]
                reservations.append(res)
        except Exception as e:
            logger.error(f"[CAC] Error reading reservation {key}: {e}")
    return reservations


def get_active_counters() -> dict:
    """Read all live active counters from Redis."""
    default_res = {"workspace_active_calls": {}, "agent_active_calls": {}, "trunk_active_calls": {}}
    if not redis_client:
        return default_res
    
    try:
        redis_client.ping()
    except Exception as e:
        logger.warning(f"[CAC] Redis is down or unreachable, returning empty active counters: {e}")
        return default_res
    
    workspace_active = {}
    agent_active = {}
    trunk_active = {}
    
    try:
        for key in redis_client.scan_iter("workspace:*:active_calls"):
            val = redis_client.get(key)
            w_id = key.split(":")[1]
            workspace_active[w_id] = int(val or 0)
            
        for key in redis_client.scan_iter("agent:*:active_calls"):
            val = redis_client.get(key)
            a_id = key.split(":")[1]
            agent_active[a_id] = int(val or 0)
            
        for key in redis_client.scan_iter("trunk:*:active_calls"):
            val = redis_client.get(key)
            t_id = key.split(":")[1]
            trunk_active[t_id] = int(val or 0)
    except Exception as e:
        logger.error(f"[CAC] Failed to read active counters from Redis: {e}")
        return default_res
        
    return {
        "workspace_active_calls": workspace_active,
        "agent_active_calls": agent_active,
        "trunk_active_calls": trunk_active
    }


async def reconcile_stale_reservations(db: Client) -> dict:
    """
    Finds call reservations that are expired (expires_at < now) and status = 'reserved',
    checks if an active Asterisk channel exists for them, and if not, releases the reservation.
    """
    logger.info("[CAC] Starting stale reservation reconciliation...")
    now_iso = datetime.now(timezone.utc).isoformat()
    
    try:
        expired_res = db.table("call_reservations")\
            .select("*")\
            .eq("status", "reserved")\
            .lt("expires_at", now_iso)\
            .execute()
    except Exception as e:
        logger.error(f"[CAC] Failed to query expired reservations from DB: {e}")
        return {"success": False, "error": str(e)}

    expired = expired_res.data or []
    if not expired:
        logger.info("[CAC] No stale reservations found.")
        return {"success": True, "released_count": 0}

    logger.info(f"[CAC] Found {len(expired)} stale reservations in DB. Checking Asterisk channels...")
    
    from app.api.v1.admin import run_safe_asterisk_cmd
    channels_output = ""
    try:
        channels_output = run_safe_asterisk_cmd("core show channels")
    except Exception as err:
        logger.error(f"[CAC] Could not retrieve Asterisk channels for reconciliation: {err}")
        pass

    released_count = 0
    for res in expired:
        call_uuid = res.get("call_uuid")
        if not call_uuid:
            continue
            
        channel_exists = False
        if channels_output and call_uuid:
            channel_exists = call_uuid in channels_output

        if not channel_exists:
            logger.warning(f"[CAC] Reconciling stale reservation {call_uuid}: no active Asterisk channel found. Releasing...")
            released = release_call_reservation(call_uuid)
            if released:
                released_count += 1
        else:
            logger.info(f"[CAC] Expired reservation {call_uuid} still has an active Asterisk channel. Keeping alive.")

    logger.info(f"[CAC] Stale reservation reconciliation finished. Released {released_count} reservations.")
    return {"success": True, "released_count": released_count}


async def reconcile_active_counters(workspace_id: Optional[str] = None) -> dict:
    """Rebuild Redis active counters from unreleased reservations without blindly setting to 0."""
    if not redis_client:
        return {"success": False, "error": "Redis offline"}
    
    db = get_supabase_client()
    
    # 1. Clean up stale reservations first
    stale_report = await reconcile_stale_reservations(db)
    stale_released = stale_report.get("released_count", 0)
    
    all_before = get_active_counters()
    reservations = get_active_reservations(workspace_id)
    
    target_workspace = {}
    target_agent = {}
    target_trunk = {}
    
    for res in reservations:
        w_id = res.get("workspace_id")
        a_id = res.get("agent_id")
        t_id = res.get("sip_trunk_provider_id") or "none"
        incremented = res.get("incremented") or {}
        
        if w_id:
            target_workspace[w_id] = target_workspace.get(w_id, 0) + (1 if incremented.get("workspace") else 0)
        if a_id:
            target_agent[a_id] = target_agent.get(a_id, 0) + (1 if incremented.get("agent") else 0)
        if t_id:
            target_trunk[t_id] = target_trunk.get(t_id, 0) + (1 if incremented.get("trunk") else 0)
            
    if workspace_id:
        before_ws = all_before["workspace_active_calls"].get(workspace_id, 0)
        after_ws = target_workspace.get(workspace_id, 0)
        redis_client.set(f"workspace:{workspace_id}:active_calls", after_ws)
        
        before_ag = {a_id: all_before["agent_active_calls"].get(a_id, 0) for a_id in target_agent.keys()}
        after_ag = {a_id: target_agent.get(a_id, 0) for a_id in target_agent.keys()}
        for a_id, count in after_ag.items():
            redis_client.set(f"agent:{a_id}:active_calls", count)
            
        before_tr = {t_id: all_before["trunk_active_calls"].get(t_id, 0) for t_id in target_trunk.keys()}
        after_tr = {t_id: target_trunk.get(t_id, 0) for t_id in target_trunk.keys()}
        for t_id, count in after_tr.items():
            redis_client.set(f"trunk:{t_id}:active_calls", count)
            
        return {
            "success": True,
            "workspace_id": workspace_id,
            "before": {
                "workspace_active_calls": before_ws,
                "agent_active_calls": before_ag,
                "trunk_active_calls": before_tr
            },
            "after": {
                "workspace_active_calls": after_ws,
                "agent_active_calls": after_ag,
                "trunk_active_calls": after_tr
            },
            "active_reservations": len(reservations),
            "stale_reservations_released": stale_released,
            "fixed": True
        }
    else:
        # Reconcile globally
        fixed_workspace = {}
        for w_id, count in target_workspace.items():
            ws_key = f"workspace:{w_id}:active_calls"
            redis_client.set(ws_key, count)
            fixed_workspace[w_id] = count
            
        fixed_agent = {}
        for a_id, count in target_agent.items():
            agent_key = f"agent:{a_id}:active_calls"
            redis_client.set(agent_key, count)
            fixed_agent[a_id] = count
            
        fixed_trunk = {}
        for t_id, count in target_trunk.items():
            trunk_key = f"trunk:{t_id}:active_calls"
            redis_client.set(trunk_key, count)
            fixed_trunk[t_id] = count
            
        # Clean any dangling keys not in target mapping to 0
        for w_id in all_before["workspace_active_calls"]:
            if w_id not in target_workspace:
                redis_client.set(f"workspace:{w_id}:active_calls", 0)
                fixed_workspace[w_id] = 0
                
        for a_id in all_before["agent_active_calls"]:
            if a_id not in target_agent:
                redis_client.set(f"agent:{a_id}:active_calls", 0)
                fixed_agent[a_id] = 0
                
        for t_id in all_before["trunk_active_calls"]:
            if t_id not in target_trunk:
                redis_client.set(f"trunk:{t_id}:active_calls", 0)
                fixed_trunk[t_id] = 0
                
        return {
            "success": True,
            "workspace_id": None,
            "before": all_before,
            "after": {
                "workspace_active_calls": fixed_workspace,
                "agent_active_calls": fixed_agent,
                "trunk_active_calls": fixed_trunk
            },
            "active_reservations": len(reservations),
            "stale_reservations_released": stale_released,
            "fixed": True
        }
