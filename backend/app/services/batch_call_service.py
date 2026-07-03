import logging
import asyncio
from datetime import datetime, timezone
from typing import List, Optional
from app.db.client import get_supabase_client, Client
from app.services.call_admission_control import check_and_reserve_call, release_call_reservation

logger = logging.getLogger(__name__)

# Track active batch task loops to allow graceful cancellation
_active_batch_tasks = {}

async def start_batch_campaign(
    workspace_id: str,
    agent_id: str,
    phone_numbers: List[str],
    admin_user_id: Optional[str] = None
) -> str:
    """Creates a new batch campaign run, queues the phone numbers, and spawns the dialer task."""
    db = get_supabase_client()
    
    # 1. Insert batch_call_runs record
    run_res = db.table("batch_call_runs").insert({
        "workspace_id": workspace_id,
        "agent_id": agent_id,
        "status": "pending",
        "total_numbers": len(phone_numbers),
        "queued_count": len(phone_numbers),
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
            "status": "queued"
        }
        for num in phone_numbers
    ]
    db.table("batch_call_items").insert(items_payload).execute()
    
    # 3. Spawn background queue processor
    task = asyncio.create_task(process_batch_run_queue(batch_run_id))
    _active_batch_tasks[batch_run_id] = task
    
    return batch_run_id


async def stop_batch_campaign(batch_run_id: str, admin_user_id: Optional[str] = None) -> bool:
    """Gracefully stops a running batch campaign, marking queued items as stopped."""
    db = get_supabase_client()
    
    # Update run status
    db.table("batch_call_runs").update({
        "status": "stopped",
        "ended_at": datetime.now(timezone.utc).isoformat()
    }).eq("id", batch_run_id).execute()
    
    # Cancel task loop
    task = _active_batch_tasks.get(batch_run_id)
    if task:
        task.cancel()
        _active_batch_tasks.pop(batch_run_id, None)
        
    # Mark all remaining queued items as stopped
    db.table("batch_call_items").update({
        "status": "failed",
        "failure_reason": "campaign_stopped_by_admin"
    }).eq("batch_run_id", batch_run_id).eq("status", "queued").execute()
    
    # Update count stats
    rebuild_batch_counters(db, batch_run_id)
    return True


def rebuild_batch_counters(db: Client, batch_run_id: str):
    """Re-calculates item status counts and updates the batch_call_runs record."""
    try:
        items_res = db.table("batch_call_items").select("status").eq("batch_run_id", batch_run_id).execute()
        items = items_res.data or []
        
        queued = sum(1 for i in items if i["status"] == "queued")
        dialing = sum(1 for i in items if i["status"] == "dialing")
        connected = sum(1 for i in items if i["status"] == "connected")
        failed = sum(1 for i in items if i["status"] == "failed")
        rejected = sum(1 for i in items if i["status"] == "rejected")
        cac_rejected = sum(1 for i in items if i["status"] == "cac_rejected")
        
        db.table("batch_call_runs").update({
            "queued_count": queued,
            "dialed_count": dialing + connected + failed,
            "connected_count": connected,
            "failed_count": failed,
            "rejected_count": rejected,
            "cac_rejected_count": cac_rejected
        }).eq("id", batch_run_id).execute()
    except Exception as e:
        logger.error(f"[Batch Campaign] Failed to rebuild counters for {batch_run_id}: {e}")


async def process_batch_run_queue(batch_run_id: str):
    """Processes campaign items sequentially with concurrency throttling and CAC validation."""
    db = get_supabase_client()
    
    # Update run state to running
    db.table("batch_call_runs").update({
        "status": "running",
        "started_at": datetime.now(timezone.utc).isoformat()
    }).eq("id", batch_run_id).execute()
    
    try:
        while True:
            # Check campaign status is still running
            run_res = db.table("batch_call_runs").select("status, workspace_id, agent_id").eq("id", batch_run_id).execute()
            if not run_res.data:
                break
                
            run = run_res.data[0]
            if run["status"] != "running":
                break
                
            workspace_id = run["workspace_id"]
            agent_id = run["agent_id"]
            
            # Fetch next queued item
            item_res = db.table("batch_call_items").select("*").eq("batch_run_id", batch_run_id).eq("status", "queued").order("created_at").limit(1).execute()
            if not item_res.data:
                # Queue completed!
                db.table("batch_call_runs").update({
                    "status": "completed",
                    "ended_at": datetime.now(timezone.utc).isoformat()
                }).eq("id", batch_run_id).execute()
                break
                
            item = item_res.data[0]
            item_id = item["id"]
            phone_number = item["phone_number"]
            
            # Create a unique call UUID
            import uuid
            call_uuid = f"batch-{uuid.uuid4()}"
            
            # 1. CAC Check
            allowed, reject_reason = await check_and_reserve_call(
                call_uuid=call_uuid,
                direction="outbound",
                workspace_id=workspace_id,
                agent_id=agent_id,
                dialed_number=phone_number
            )
            
            if not allowed:
                # Mark as CAC rejected
                db.table("batch_call_items").update({
                    "status": "cac_rejected",
                    "rejection_reason": reject_reason,
                    "ended_at": datetime.now(timezone.utc).isoformat()
                }).eq("id", item_id).execute()
                
                rebuild_batch_counters(db, batch_run_id)
                await asyncio.sleep(1) # short throttle sleep before next dial
                continue
                
            # 2. Dial Outward via Asterisk
            db.table("batch_call_items").update({
                "status": "dialing",
                "call_uuid": call_uuid,
                "started_at": datetime.now(timezone.utc).isoformat()
            }).eq("id", item_id).execute()
            
            rebuild_batch_counters(db, batch_run_id)
            
            # Trigger originate in Asterisk
            try:
                # Import originate runner
                from app.api.v1.calls import asterisk_outbound_call
                dial_success = await asterisk_outbound_call(
                    call_uuid=call_uuid,
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                    phone_number=phone_number
                )
                
                if dial_success:
                    # Mark connected (actual call progress tracking will be handled by session loops)
                    db.table("batch_call_items").update({
                        "status": "connected"
                    }).eq("id", item_id).execute()
                else:
                    # Originate failed
                    release_call_reservation(call_uuid)
                    db.table("batch_call_items").update({
                        "status": "failed",
                        "failure_reason": "originate_failed",
                        "ended_at": datetime.now(timezone.utc).isoformat()
                    }).eq("id", item_id).execute()
            except Exception as e:
                logger.error(f"[Batch Campaign] Dial error: {e}")
                release_call_reservation(call_uuid)
                db.table("batch_call_items").update({
                    "status": "failed",
                    "failure_reason": str(e),
                    "ended_at": datetime.now(timezone.utc).isoformat()
                }).eq("id", item_id).execute()
                
            rebuild_batch_counters(db, batch_run_id)
            
            # Sequential Throttle: Sleep 2 seconds before launching the next dial
            await asyncio.sleep(2)
            
    except asyncio.CancelledError:
        logger.info(f"[Batch Campaign] Background loop task cancelled for campaign {batch_run_id}")
    except Exception as e:
        logger.error(f"[Batch Campaign] Error in processing queue loop for {batch_run_id}: {e}")
        db.table("batch_call_runs").update({"status": "failed"}).eq("id", batch_run_id).execute()
    finally:
        _active_batch_tasks.pop(batch_run_id, None)
