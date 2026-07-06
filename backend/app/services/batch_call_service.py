import logging
import asyncio
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Tuple
from app.db.client import get_supabase_client, Client
from app.services.call_admission_control import check_and_reserve_call, release_call_reservation

logger = logging.getLogger(__name__)

# Track active batch task loops to allow graceful cancellation/pause
_active_batch_tasks = {}

def get_retry_policy(reason: str, current_attempts: int) -> Tuple[bool, int, str]:
    """
    Returns (should_retry, delay_seconds, new_status)
    based on the failure or CAC rejection reason.
    """
    # Permanent rejections
    permanent_rejections = {
        "workspace_suspended",
        "out_of_credits",
        "monthly_minutes_exhausted",
        "outbound_disabled",
        "invalid_agent",
        "agent_not_found",
        "agent_inactive",
        "no_active_did",
        "invalid_number",
        "permission_denied",
        "workspace_not_found",
        "trunk_not_found",
        "trunk_inactive"
    }
    
    if reason in permanent_rejections:
        if reason == "invalid_number":
            return False, 0, "invalid_number"
        return False, 0, "cac_rejected"
        
    # Check attempts
    if "concurrency" in reason:
        # Concurrency rejections retry after 1-2 minutes, no hard attempt limit
        return True, 60, "retry_later"
    elif reason in ("busy", "BUSY"):
        max_attempts = 2
        delay = 15 * 60
    elif reason in ("no_answer", "NOANSWER"):
        max_attempts = 2
        delay = 30 * 60
    elif reason in ("originate_temporarily_failed", "failed", "originate_failed", "failure"):
        max_attempts = 3
        delay = 5 * 60
    elif reason == "provider_rate_limited":
        max_attempts = 3
        delay = 5 * 60
    else:
        # Default fallback for temporary errors
        max_attempts = 2
        delay = 5 * 60
        
    if current_attempts < max_attempts:
        return True, delay, "retry_later"
    else:
        return False, 0, "failed"


async def start_batch_campaign(
    workspace_id: str,
    agent_id: str,
    phone_numbers: List[str],
    admin_user_id: Optional[str] = None,
    max_parallel_calls: int = 1,
    dry_run: bool = False
) -> str:
    """Creates a new batch campaign run in queued status, inserts numbers, and starts worker."""
    db = get_supabase_client()
    
    # 1. Insert batch_call_runs record with status 'queued'
    run_res = db.table("batch_call_runs").insert({
        "workspace_id": workspace_id,
        "agent_id": agent_id,
        "status": "queued",
        "total_numbers": len(phone_numbers),
        "queued_count": len(phone_numbers),
        "max_parallel_calls": max_parallel_calls,
        "dry_run": dry_run,
        "metadata": {"created_by": admin_user_id}
    }).execute()
    
    batch_run_id = run_res.data[0]["id"]
    
    # 2. Bulk insert batch_call_items
    items_payload = [
        {
            "batch_run_id": batch_run_id,
            "workspace_id": workspace_id,
            "agent_id": agent_id,
            "phone_number": num,
            "status": "queued",
            "attempt_count": 0,
            "max_attempts": 2
        }
        for num in phone_numbers
    ]
    db.table("batch_call_items").insert(items_payload).execute()
    
    # 3. Spawn background queue processor
    task = asyncio.create_task(process_batch_run_queue(batch_run_id))
    _active_batch_tasks[batch_run_id] = task
    
    return batch_run_id


async def stop_batch_campaign(batch_run_id: str, admin_user_id: Optional[str] = None) -> bool:
    """Gracefully stops/cancels a running batch campaign."""
    db = get_supabase_client()
    
    # Update run status to cancelled
    db.table("batch_call_runs").update({
        "status": "cancelled",
        "ended_at": datetime.now(timezone.utc).isoformat()
    }).eq("id", batch_run_id).execute()
    
    # Cancel task loop
    task = _active_batch_tasks.get(batch_run_id)
    if task:
        task.cancel()
        _active_batch_tasks.pop(batch_run_id, None)
        
    # Mark remaining queued/retry_later items as cancelled
    db.table("batch_call_items").update({
        "status": "cancelled",
        "ended_at": datetime.now(timezone.utc).isoformat()
    }).eq("batch_run_id", batch_run_id).in_("status", ["queued", "retry_later"]).execute()
    
    rebuild_batch_counters(db, batch_run_id)
    return True


async def pause_batch_campaign(batch_run_id: str, admin_user_id: Optional[str] = None) -> bool:
    """Pauses a running batch campaign run."""
    db = get_supabase_client()
    
    res = db.table("batch_call_runs").update({
        "status": "paused"
    }).eq("id", batch_run_id).eq("status", "running").execute()
    
    if not res.data:
        return False
        
    # Cancel task loop
    task = _active_batch_tasks.get(batch_run_id)
    if task:
        task.cancel()
        _active_batch_tasks.pop(batch_run_id, None)
        
    rebuild_batch_counters(db, batch_run_id)
    return True


async def resume_batch_campaign(batch_run_id: str, admin_user_id: Optional[str] = None) -> bool:
    """Resumes a paused batch campaign run."""
    # Spawn background queue processor
    task = asyncio.create_task(process_batch_run_queue(batch_run_id))
    _active_batch_tasks[batch_run_id] = task
    return True


def rebuild_batch_counters(db: Client, batch_run_id: str):
    """Re-calculates item status counts and updates the batch_call_runs record."""
    try:
        items_res = db.table("batch_call_items").select("status, attempt_count").eq("batch_run_id", batch_run_id).execute()
        items = items_res.data or []
        
        queued = sum(1 for i in items if i["status"] == "queued")
        dialing = sum(1 for i in items if i["status"] == "dialing")
        connected = sum(1 for i in items if i["status"] == "connected")
        failed = sum(1 for i in items if i["status"] == "failed")
        rejected = sum(1 for i in items if i["status"] == "rejected")
        cac_rejected = sum(1 for i in items if i["status"] == "cac_rejected")
        completed = sum(1 for i in items if i["status"] == "completed")
        retry_later = sum(1 for i in items if i["status"] == "retry_later")
        invalid_number = sum(1 for i in items if i["status"] == "invalid_number")
        cancelled = sum(1 for i in items if i["status"] == "cancelled")
        
        attempted = sum(1 for i in items if (i.get("attempt_count") or 0) > 0)
        
        db.table("batch_call_runs").update({
            "queued_count": queued,
            "dialed_count": dialing + connected + failed + completed + retry_later + invalid_number + cancelled,
            "connected_count": connected,
            "failed_count": failed,
            "rejected_count": rejected + invalid_number,
            "cac_rejected_count": cac_rejected,
            "attempted_count": attempted,
            "completed_count": completed,
            "retry_count": retry_later,
            "cancelled_count": cancelled
        }).eq("id", batch_run_id).execute()
    except Exception as e:
        logger.error(f"[Batch Campaign] Failed to rebuild counters for {batch_run_id}: {e}")


async def process_batch_run_queue(batch_run_id: str):
    """Processes campaign items concurrently with atomic locks, pacing, and retry checks."""
    db = get_supabase_client()
    
    # Atomic campaign start lock
    run_res = db.table("batch_call_runs").select("status, started_at").eq("id", batch_run_id).execute()
    if not run_res.data:
        return
    run = run_res.data[0]
    
    now_iso = datetime.now(timezone.utc).isoformat()
    started_at_val = run.get("started_at") or now_iso
    
    update_res = db.table("batch_call_runs").update({
        "status": "running",
        "started_at": started_at_val
    }).eq("id", batch_run_id).in_("status", ["queued", "paused"]).execute()
    
    if not update_res.data:
        logger.info(f"[Batch Campaign] Campaign {batch_run_id} was already claimed by another worker or not runable.")
        return

    import uuid
    worker_instance_id = str(uuid.uuid4())
    logger.info(f"[Batch Campaign] Starting campaign loop for campaign_run_id={batch_run_id} worker_instance_id={worker_instance_id}")
    
    try:
        while True:
            # 1. Fetch live status of campaign run
            run_res = db.table("batch_call_runs").select("*").eq("id", batch_run_id).execute()
            if not run_res.data:
                break
            run = run_res.data[0]
            status = run["status"]
            
            # Handle campaign pauses or aborts
            if status == "paused":
                logger.info(f"[Batch Campaign] Run {batch_run_id} is paused. Stopping worker loop.")
                break
            elif status in ("cancelled", "stopped", "failed"):
                logger.info(f"[Batch Campaign] Run {batch_run_id} was cancelled/stopped. Cancelling queued items.")
                db.table("batch_call_items").update({
                    "status": "cancelled",
                    "ended_at": datetime.now(timezone.utc).isoformat()
                }).eq("batch_run_id", batch_run_id).in_("status", ["queued", "retry_later"]).execute()
                break

            # 2. Count active calls for this run
            active_res = db.table("batch_call_items").select("id", count="exact").eq("batch_run_id", batch_run_id).in_("status", ["dialing", "connected"]).execute()
            active_calls = active_res.count if active_res.count is not None else 0
            
            max_parallel = run.get("max_parallel_calls") or 1
            if active_calls >= max_parallel:
                await asyncio.sleep(1)
                continue
                
            # 3. Fetch next ready item
            now_iso = datetime.now(timezone.utc).isoformat()
            item_res = db.table("batch_call_items") \
                .select("*") \
                .eq("batch_run_id", batch_run_id) \
                .in_("status", ["queued", "retry_later"]) \
                .or_(f"next_attempt_at.is.null,next_attempt_at.lte.{now_iso}") \
                .order("created_at") \
                .limit(1) \
                .execute()
                
            if not item_res.data:
                # No queued or retry_later ready right now. Check if campaign is finished
                future_res = db.table("batch_call_items").select("id", count="exact").eq("batch_run_id", batch_run_id).eq("status", "retry_later").execute()
                future_count = future_res.count if future_res.count is not None else 0
                
                if active_calls == 0 and future_count == 0:
                    # Fully completed!
                    db.table("batch_call_runs").update({
                        "status": "completed",
                        "ended_at": datetime.now(timezone.utc).isoformat()
                    }).eq("id", batch_run_id).execute()
                    logger.info(f"[Batch Campaign] Campaign {batch_run_id} completed successfully.")
                    break
                else:
                    # Wait for active calls or retry schedules
                    await asyncio.sleep(2)
                    continue
                    
            item = item_res.data[0]
            item_id = item["id"]
            
            # 4. Atomic claim lock
            lock_res = db.table("batch_call_items").update({
                "status": "dialing",
                "locked_at": now_iso,
                "attempt_count": (item.get("attempt_count") or 0) + 1,
                "started_at": now_iso
            }).eq("id", item_id).in_("status", ["queued", "retry_later"]).or_(f"next_attempt_at.is.null,next_attempt_at.lte.{now_iso}").execute()
            
            if not lock_res.data:
                # Lock conflict, try again
                continue
                
            # 5. Spawn background dialer task for this item
            asyncio.create_task(dial_batch_item(db, run, item_id, item.get("attempt_count") or 0))
            
            # Pacing sleep
            await asyncio.sleep(0.5)
            
    except asyncio.CancelledError:
        logger.info(f"[Batch Campaign] Background loop task cancelled for campaign {batch_run_id}")
    except Exception as e:
        logger.error(f"[Batch Campaign] Error in processing queue loop for {batch_run_id}: {e}")
        db.table("batch_call_runs").update({"status": "failed"}).eq("id", batch_run_id).execute()
    finally:
        _active_batch_tasks.pop(batch_run_id, None)


async def dial_batch_item(db: Client, run: dict, item_id: str, attempt_idx: int):
    """CAC verification, Asterisk originate, and retry policy handler for an item."""
    batch_run_id = run["id"]
    workspace_id = run["workspace_id"]
    agent_id = run["agent_id"]
    
    # Fetch phone number
    item_res = db.table("batch_call_items").select("phone_number").eq("id", item_id).execute()
    if not item_res.data:
        return
    phone_number = item_res.data[0]["phone_number"]
    
    # Create unique call UUID
    import uuid
    call_uuid = f"batch-{uuid.uuid4()}"
    
    # Set item call_uuid
    db.table("batch_call_items").update({
        "call_uuid": call_uuid
    }).eq("id", item_id).execute()
    
    logger.info(f"[Batch Campaign] Dialing item {item_id} (number={phone_number}), call_uuid={call_uuid}, attempt={attempt_idx+1}")
    
    # 1. Safety Preflight (First step!)
    from app.services.outbound_safety_service import verify_outbound_dial_safety
    dry_run = run.get("dry_run", False)
    safety = await verify_outbound_dial_safety(
        workspace_id=workspace_id,
        agent_id=agent_id,
        phone_number=phone_number,
        call_uuid=call_uuid,
        batch_run_id=batch_run_id,
        batch_item_id=item_id,
        dry_run=dry_run
    )
    
    if not safety.allowed:
        logger.warning(f"[Batch Campaign] Safety preflight rejected call_uuid={call_uuid}, reason_code={safety.reason_code}")
        # Save safety tracking in DB
        db.table("batch_call_items").update({
            "safety_result": safety.dict(),
            "safety_reason_code": safety.reason_code,
            "safety_blocked_at": datetime.now(timezone.utc).isoformat()
        }).eq("id", item_id).execute()
        
        # Revert or pause campaign based on preflight result
        if safety.should_pause_campaign:
            logger.error(f"[Batch Campaign] Workspace-level fatal safety issue: {safety.reason_code}. Pausing campaign.")
            db.table("batch_call_runs").update({
                "status": "paused",
                "metadata": {"pause_reason": safety.reason_code}
            }).eq("id", batch_run_id).execute()
            
            db.table("batch_call_items").update({
                "status": "queued",
                "attempt_count": attempt_idx,
                "locked_at": None,
                "started_at": None
            }).eq("id", item_id).execute()
        elif not safety.safe_to_retry:
            # Permanent item error
            db.table("batch_call_items").update({
                "status": "cac_rejected" if safety.reason_code == "invalid_number" else "failed",
                "last_cac_reason": safety.reason_code,
                "ended_at": datetime.now(timezone.utc).isoformat()
            }).eq("id", item_id).execute()
        else:
            # Temporary error
            should_retry, delay, new_status = get_retry_policy(safety.reason_code, attempt_idx + 1)
            update_payload = {
                "status": new_status,
                "last_cac_reason": safety.reason_code,
                "ended_at": datetime.now(timezone.utc).isoformat()
            }
            if should_retry:
                update_payload["next_attempt_at"] = (datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat()
            db.table("batch_call_items").update(update_payload).eq("id", item_id).execute()
            
        rebuild_batch_counters(db, batch_run_id)
        return

    if dry_run:
        # Dry-run validation success! Exit early without reserving or originating.
        db.table("batch_call_items").update({
            "status": "completed",
            "safety_result": {"status": "dry_run_passed"},
            "safety_reason_code": "dry_run_passed",
            "ended_at": datetime.now(timezone.utc).isoformat()
        }).eq("id", item_id).execute()
        rebuild_batch_counters(db, batch_run_id)
        return

    # 2. CAC reservation check
    allowed, reject_reason = await check_and_reserve_call(
        call_uuid=call_uuid,
        direction="outbound",
        workspace_id=workspace_id,
        agent_id=agent_id,
        dialed_number=phone_number
    )
    
    if not allowed:
        logger.warning(f"[Batch Campaign] CAC check rejected call_uuid={call_uuid}, reason={reject_reason}")
        
        # Check if workspace-level fatal error -> Pause campaign
        workspace_fatal_reasons = {
            "workspace_suspended",
            "out_of_credits",
            "monthly_minutes_exhausted",
            "outbound_disabled",
            "workspace_not_found"
        }
        
        if reject_reason in workspace_fatal_reasons:
            logger.error(f"[Batch Campaign] Workspace-level fatal error {reject_reason}. Pausing campaign {batch_run_id}.")
            
            # Pause campaign atomically
            db.table("batch_call_runs").update({
                "status": "paused",
                "metadata": {"pause_reason": reject_reason}
            }).eq("id", batch_run_id).execute()
            
            # Revert item to queued state
            db.table("batch_call_items").update({
                "status": "queued",
                "attempt_count": attempt_idx,
                "last_cac_reason": reject_reason,
                "locked_at": None,
                "started_at": None
            }).eq("id", item_id).execute()
            
            rebuild_batch_counters(db, batch_run_id)
            return

        # Regular temporary/permanent rejection
        should_retry, delay, new_status = get_retry_policy(reject_reason, attempt_idx + 1)
        
        update_payload = {
            "status": new_status,
            "last_cac_reason": reject_reason,
            "ended_at": datetime.now(timezone.utc).isoformat()
        }
        if should_retry:
            update_payload["next_attempt_at"] = (datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat()
            
        db.table("batch_call_items").update(update_payload).eq("id", item_id).execute()
        rebuild_batch_counters(db, batch_run_id)
        return

    # 3. Reservation succeeded, dial outbound via Asterisk
    db.table("batch_call_items").update({
        "status": "dialing",
        "started_at": datetime.now(timezone.utc).isoformat()
    }).eq("id", item_id).execute()
    
    rebuild_batch_counters(db, batch_run_id)
    
    try:
        from_number = None
        did_res = db.table("did_numbers").select("phone_number").eq("agent_id", agent_id).eq("status", "active").execute()
        if did_res.data:
            from_number = did_res.data[0].get("phone_number")
        else:
            phone_res = db.table("phone_numbers").select("phone_number").eq("agent_id", agent_id).eq("status", "active").execute()
            if phone_res.data:
                from_number = phone_res.data[0].get("phone_number")

        from app.api.v1.calls import asterisk_outbound_call
        dial_res = await asterisk_outbound_call(
            body={
                "call_id": call_uuid,
                "workspace_id": workspace_id,
                "agent_id": agent_id,
                "to_number": phone_number,
                "from_number": from_number,
                "batch_run_id": batch_run_id,
                "batch_item_id": item_id
            },
            db=db
        )
        
        dial_success = isinstance(dial_res, dict) and dial_res.get("status") == "calling"
        
        if dial_success:
            # Register session completion cleanup callback to map final status
            def make_cleanup_callback(c_uuid, i_id, run_id):
                def cleanup_cb(call_id):
                    def update_batch_item_sync():
                        try:
                            # Read call outcome from calls table
                            call_res = db.table("calls").select("status, hangup_reason, duration_seconds").eq("call_uuid", c_uuid).execute()
                            if call_res.data:
                                call_row = call_res.data[0]
                                hangup_reason = call_row.get("hangup_reason")
                                db_status = call_row.get("status")
                                duration = call_row.get("duration_seconds") or 0
                                
                                final_status = "completed"
                                if hangup_reason in ("busy", "BUSY"):
                                    final_status = "busy"
                                elif hangup_reason in ("no_answer", "NOANSWER"):
                                    final_status = "no_answer"
                                elif hangup_reason in ("congestion", "congestion_failed", "unreachable", "failed", "error", "originate_failed"):
                                    final_status = "failed"
                                    
                                if db_status == "failed" and final_status == "completed":
                                    final_status = "failed"
                                    
                                should_retry, delay, new_status = get_retry_policy(final_status, attempt_idx + 1)
                                
                                up_payload = {
                                    "status": new_status,
                                    "ended_at": datetime.now(timezone.utc).isoformat(),
                                    "failure_reason": hangup_reason or "call_ended"
                                }
                                if should_retry:
                                    up_payload["next_attempt_at"] = (datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat()
                                    
                                db.table("batch_call_items").update(up_payload).eq("id", i_id).execute()
                            else:
                                db.table("batch_call_items").update({
                                    "status": "completed",
                                    "ended_at": datetime.now(timezone.utc).isoformat()
                                }).eq("id", i_id).execute()
                                
                            rebuild_batch_counters(db, run_id)
                        except Exception as err:
                            logger.error(f"[Batch Callback] Error updating batch item: {err}")
                            
                    asyncio.get_event_loop().run_in_executor(None, update_batch_item_sync)
                return cleanup_cb
                
            from app.services.call_session_manager import call_session_manager
            call_session_manager.register_cleanup_callback(call_uuid, make_cleanup_callback(call_uuid, item_id, batch_run_id))
            
            # Keep as connected dialing slot
            db.table("batch_call_items").update({
                "status": "connected"
            }).eq("id", item_id).execute()
            
        else:
            # Originate failed (success False)
            release_call_reservation(call_uuid)
            should_retry, delay, new_status = get_retry_policy("originate_temporarily_failed", attempt_idx + 1)
            
            update_payload = {
                "status": new_status,
                "failure_reason": "originate_failed",
                "ended_at": datetime.now(timezone.utc).isoformat()
            }
            if should_retry:
                update_payload["next_attempt_at"] = (datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat()
                
            db.table("batch_call_items").update(update_payload).eq("id", item_id).execute()
            
    except Exception as e:
        logger.error(f"[Batch Campaign] Dial error: {e}")
        release_call_reservation(call_uuid)
        
        should_retry, delay, new_status = get_retry_policy("originate_temporarily_failed", attempt_idx + 1)
        
        update_payload = {
            "status": new_status,
            "failure_reason": str(e),
            "ended_at": datetime.now(timezone.utc).isoformat()
        }
        if should_retry:
            update_payload["next_attempt_at"] = (datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat()
            
        db.table("batch_call_items").update(update_payload).eq("id", item_id).execute()
        
    rebuild_batch_counters(db, batch_run_id)
