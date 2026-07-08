import logging
import asyncio
from datetime import datetime, timezone
from typing import Optional
from dateutil.rrule import rrulestr
from app.core.celery_app import celery_app
from app.db.client import get_supabase_client
from .voice_tasks import execute_voice_call, execute_webhook, run_voice_call, run_webhook

logger = logging.getLogger(__name__)

def calculate_next_run(rrule_str: str, from_date: datetime) -> Optional[datetime]:
    try:
        if from_date.tzinfo is None:
            from_date = from_date.replace(tzinfo=timezone.utc)
        rule = rrulestr(rrule_str)
        next_run = rule.after(from_date)
        if next_run and next_run.tzinfo is None:
            next_run = next_run.replace(tzinfo=timezone.utc)
        return next_run
    except Exception as e:
        logger.error(f"Failed next run calculation: {e}")
        return None

def poll_and_dispatch(use_celery: bool = True):
    """
    Core polling logic. 
    If use_celery=True, dispatches to Celery workers.
    If use_celery=False, executes immediately in the current thread (useful for dev/no-redis).
    """
    # Periodically clean up any stale call sessions that never connected to AudioSocket
    try:
        from app.services.call_session_manager import call_session_manager
        call_session_manager.cleanup_stale_calls(timeout_seconds=120)
    except Exception as e:
        logger.error(f"[Scheduler] Failed to clean up stale calls: {e}")

    db = get_supabase_client()
    now_obj = datetime.now(timezone.utc)
    now_iso = now_obj.isoformat()
    
    result = db.table("scheduled_tasks")\
        .select("*")\
        .eq("status", "scheduled")\
        .lte("next_run_at", now_iso)\
        .execute()
    
    tasks = result.data or []
    if not tasks:
        return 0

    count = 0
    for task in tasks:
        task_id = task["id"]
        
        # Atomic lock
        update_res = db.table("scheduled_tasks")\
            .update({"status": "running", "last_run_at": now_iso})\
            .eq("id", task_id)\
            .eq("status", "scheduled")\
            .execute()
            
        if not update_res.data:
            continue

        if use_celery:
            if task["task_type"] == "voice_call":
                execute_voice_call.delay(task_id, task["payload"])
            elif task["task_type"] == "webhook":
                execute_webhook.delay(task_id, task["payload"])
        else:
            # Synchronous fallback for local dev
            if task["task_type"] == "voice_call":
                run_voice_call(task_id, task["payload"])
            elif task["task_type"] == "webhook":
                run_webhook(task_id, task["payload"])
        
        count += 1
    return count

@celery_app.task
def poll_scheduled_tasks():
    return f"Dispatched {poll_and_dispatch(use_celery=True)} tasks"

async def start_local_scheduler():
    """A simple background loop for dev environments without Redis."""
    logger.info("Starting local fallback scheduler loop (no Redis required)")
    while True:
        try:
            count = poll_and_dispatch(use_celery=False)
            if count > 0:
                logger.info(f"Local Scheduler: Executed {count} tasks")
        except Exception as e:
            logger.error(f"Local Scheduler Error: {e}")
        await asyncio.sleep(60)
