import logging
import re
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List
from app.db.client import get_supabase_client, Client

logger = logging.getLogger(__name__)

def log_provider_health_event(
    provider: str,
    service_type: str,
    status: str,
    latency_ms: Optional[int] = None,
    error_code: Optional[str] = None,
    error_message: Optional[str] = None,
    workspace_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    call_uuid: Optional[str] = None,
    metadata: Optional[dict] = None
) -> None:
    """Logs provider health metrics asynchronously or synchronously to provider_health_events table."""
    try:
        db = get_supabase_client()
        sanitized_msg = None
        if error_message:
            # Clean any potential token/secret leakage from error messages (mask sk- or Bearer tokens)
            sanitized_msg = re.sub(r"(sk-[a-zA-Z0-9]{12,}|Bearer\s+[a-zA-Z0-9\-\._~+/]+=*)", "********", error_message)
            sanitized_msg = sanitized_msg[:500]

        # Safety constraint check
        valid_status = status if status in ('success', 'failure', '429_rate_limited') else 'failure'

        db.table("provider_health_events").insert({
            "provider": provider,
            "service_type": service_type,
            "status": valid_status,
            "latency_ms": latency_ms,
            "error_code": error_code,
            "error_message": sanitized_msg,
            "workspace_id": workspace_id,
            "agent_id": agent_id,
            "call_uuid": call_uuid,
            "metadata": metadata or {}
        }).execute()
        logger.debug(f"[ProviderHealth] Logged provider={provider} status={valid_status} latency={latency_ms}ms")
    except Exception as e:
        logger.error(f"[ProviderHealth] Failed to log provider health event: {e}")

def get_provider_health_summary(db: Client) -> list:
    """Aggregates error counts and request volumes for STT, LLM, TTS providers over the last 24h.
    Returns a list of ProviderMetric objects matching the frontend interface."""
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    try:
        res = db.table("provider_health_events").select("provider, service_type, status, latency_ms").gte("created_at", since).execute()
        summary: Dict[tuple, dict] = {}
        for row in res.data:
            prov = row["provider"]
            svc = row.get("service_type") or "unknown"
            status = row["status"]
            lat = row["latency_ms"] or 0
            key = (prov, svc)

            if key not in summary:
                summary[key] = {"provider": prov, "service_type": svc, "success": 0, "failure": 0, "total": 0, "total_latency": 0, "latency_count": 0}

            summary[key]["total"] += 1
            if status == "success":
                summary[key]["success"] += 1
            else:
                summary[key]["failure"] += 1

            if lat > 0:
                summary[key]["total_latency"] += lat
                summary[key]["latency_count"] += 1

        results = []
        for stats in summary.values():
            avg_lat = 0
            if stats["latency_count"] > 0:
                avg_lat = round(stats["total_latency"] / stats["latency_count"], 2)
            success_rate = round((stats["success"] / stats["total"]) * 100, 2) if stats["total"] > 0 else 100.0
            results.append({
                "provider": stats["provider"],
                "service_type": stats["service_type"],
                "avg_latency": avg_lat,
                "total_requests": stats["total"],
                "error_count": stats["failure"],
                "success_rate": success_rate,
            })
        return results
    except Exception as e:
        logger.error(f"[ProviderHealth] Failed to get health summary: {e}")
        return []

def get_provider_health_events(db: Client, limit: int = 50, offset: int = 0) -> list:
    """Returns detailed provider health error traces with pagination support."""
    try:
        res = db.table("provider_health_events").select("*").order("created_at", desc=True).range(offset, offset + limit - 1).execute()
        return res.data
    except Exception as e:
        logger.error(f"[ProviderHealth] Failed to query events: {e}")
        return []

def get_provider_latency_summary(db: Client) -> list:
    """Returns breakdown of average latencies over the last 24 hours."""
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    try:
        res = db.table("provider_health_events").select("provider, service_type, latency_ms").gte("created_at", since).execute()
        latencies = {}
        for row in res.data:
            key = (row["provider"], row["service_type"])
            lat = row["latency_ms"]
            if lat is not None and lat > 0:
                if key not in latencies:
                    latencies[key] = []
                latencies[key].append(lat)
                
        results = []
        for (prov, srv), lats in latencies.items():
            avg_lat = sum(lats) / len(lats)
            results.append({
                "provider": prov,
                "service_type": srv,
                "average_latency_ms": round(avg_lat, 2),
                "samples": len(lats)
            })
        return results
    except Exception as e:
        logger.error(f"[ProviderHealth] Failed to calculate latency summary: {e}")
        return []

def cleanup_old_provider_health_events(db: Client, retention_days: int = 30) -> int:
    """Deletes provider health records older than retention_days."""
    limit_date = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
    try:
        res = db.table("provider_health_events").delete().lt("created_at", limit_date).execute()
        count = len(res.data) if res.data else 0
        logger.info(f"[Cleanup] Deleted {count} old provider health events older than {retention_days} days.")
        return count
    except Exception as e:
        logger.error(f"[Cleanup] Failed to clean provider health logs: {e}")
        return 0
