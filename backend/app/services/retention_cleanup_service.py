import logging
from datetime import datetime, timezone, timedelta
from app.db.client import get_supabase_client, Client

logger = logging.getLogger(__name__)

def run_retention_cleanup() -> dict:
    """Dispatches database cleanup tasks based on data retention policies."""
    db = get_supabase_client()
    results = {}
    
    # 1. Clean provider health events older than 30 days
    try:
        from app.services.provider_health_service import cleanup_old_provider_health_events
        deleted_health = cleanup_old_provider_health_events(db, retention_days=30)
        results["provider_health_events_deleted"] = deleted_health
    except Exception as e:
        logger.error(f"[Cleanup] Provider health cleanup failed: {e}")
        results["provider_health_events_deleted"] = 0

    # 2. Clean call limit events older than 90 days
    try:
        limit_date = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
        res = db.table("call_limit_events").delete().lt("created_at", limit_date).execute()
        deleted_limits = len(res.data) if res.data else 0
        results["call_limit_events_deleted"] = deleted_limits
        logger.info(f"[Cleanup] Deleted {deleted_limits} call limit events older than 90 days.")
    except Exception as e:
        logger.error(f"[Cleanup] Call limit events cleanup failed: {e}")
        results["call_limit_events_deleted"] = 0

    return results
