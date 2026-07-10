import logging
from fastapi import APIRouter, Depends, HTTPException
from typing import Dict, Any
from app.db.client import get_db, Client

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/setup")
async def setup_workspace(data: Dict[str, Any], db: Client = Depends(get_db)):
    """
    Get-or-create a default workspace for a user.
    Uses upsert so it's safe to call multiple times.
    """
    user_id = data.get("user_id")
    email = data.get("email", "")

    if not user_id:
        raise HTTPException(status_code=400, detail="user_id required")

    try:
        # Check if workspace already exists first to avoid slow DB writes on every setup call
        logger.info(f"[setup] checking existing workspace for {user_id}")
        existing = db.table("workspaces").select("id").eq("owner_id", user_id).limit(1).execute()
        if existing.data:
            logger.info(f"[setup] found existing workspace {existing.data[0]['id']}")
            return {"workspace_id": existing.data[0]["id"]}

        # If no workspace exists, upsert profile and create default workspace
        logger.info(f"[setup] upserting profile for {user_id}")
        try:
            db.table("profiles").upsert(
                {"id": user_id, "email": email, "role": "user"},
                on_conflict="id"
            ).execute()
        except Exception as profile_err:
            # Profile may already exist or role column may differ — log but continue
            logger.warning(f"[setup] profile upsert warning (non-fatal): {profile_err}")

        logger.info(f"[setup] creating workspace")
        workspace = db.table("workspaces").insert({
            "name": "Default Workspace",
            "owner_id": user_id,
        }).execute()

        workspace_id = workspace.data[0]["id"]
        logger.info(f"[setup] created workspace {workspace_id}")
        return {"workspace_id": workspace_id}

    except Exception as e:
        logger.error(f"[setup] ERROR: {e}", exc_info=True)
        from app.core.config import settings
        if settings.environment == "development" and ("foreign key" in str(e).lower() or "violates" in str(e).lower() or "not present" in str(e).lower()):
            logger.warning(f"[setup] Setup failed due to FK constraint. Finding a fallback profile in DB...")
            try:
                fallback_profiles = db.table("profiles").select("id").limit(1).execute()
                if fallback_profiles.data:
                    fallback_uid = fallback_profiles.data[0]["id"]
                    logger.warning(f"[setup] Found fallback profile {fallback_uid}. Getting its workspace...")
                    fb_ws = db.table("workspaces").select("id").eq("owner_id", fallback_uid).limit(1).execute()
                    if fb_ws.data:
                        logger.warning(f"[setup] Returning fallback workspace {fb_ws.data[0]['id']}")
                        return {"workspace_id": fb_ws.data[0]["id"]}
                    else:
                        # Create a workspace for the fallback profile
                        workspace = db.table("workspaces").insert({
                            "name": "Default Workspace",
                            "owner_id": fallback_uid,
                        }).execute()
                        logger.warning(f"[setup] Created fallback workspace {workspace.data[0]['id']}")
                        return {"workspace_id": workspace.data[0]["id"]}
            except Exception as fallback_err:
                logger.error(f"[setup] Fallback failed: {fallback_err}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{workspace_id}/schedules")
async def get_workspace_schedules(workspace_id: str, db: Client = Depends(get_db)):
    """Fetch all scheduled tasks for a specific workspace."""
    try:
        result = db.table("scheduled_tasks").select("*").eq("workspace_id", workspace_id).execute()
        return result.data
    except Exception as e:
        logger.error(f"[schedules] ERROR: {e}")
        raise HTTPException(status_code=500, detail=str(e))


from pydantic import BaseModel
from typing import Optional
from app.utils.auth import verify_workspace_access

class WorkspaceSettingsUpdate(BaseModel):
    name: Optional[str] = None
    timezone: Optional[str] = None
    billing_email: Optional[str] = None
    webhook_url: Optional[str] = None

@router.get("/{workspace_id}/settings", dependencies=[Depends(verify_workspace_access)])
async def get_workspace_settings(workspace_id: str, db: Client = Depends(get_db)):
    """Fetch settings for a specific workspace."""
    try:
        res = db.table("workspaces").select("id, name, timezone, billing_email, webhook_url, owner_id").eq("id", workspace_id).execute()
        if not res.data:
            raise HTTPException(status_code=404, detail="Workspace not found")
        return res.data[0]
    except Exception as e:
        logger.error(f"[get_settings] ERROR: {e}")
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=str(e))

@router.patch("/{workspace_id}/settings", dependencies=[Depends(verify_workspace_access)])
async def update_workspace_settings(
    workspace_id: str,
    settings_data: WorkspaceSettingsUpdate,
    db: Client = Depends(get_db)
):
    """Update settings for a specific workspace."""
    try:
        res = db.table("workspaces").select("id").eq("id", workspace_id).execute()
        if not res.data:
            raise HTTPException(status_code=404, detail="Workspace not found")
        
        update_dict = settings_data.dict(exclude_unset=True)
        if not update_dict:
            return {"status": "no-op"}
            
        update_res = db.table("workspaces").update(update_dict).eq("id", workspace_id).execute()
        return update_res.data[0]
    except Exception as e:
        logger.error(f"[update_settings] ERROR: {e}")
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{workspace_id}/billing", dependencies=[Depends(verify_workspace_access)])
async def get_workspace_billing(workspace_id: str, db: Client = Depends(get_db)):
    """Fetch usage limits and consumed minutes for a workspace in the current billing cycle."""
    try:
        # 1. Fetch workspace limits
        limits_res = db.table("workspace_limits").select("monthly_minute_limit, max_concurrent_calls, billing_status").eq("workspace_id", workspace_id).execute()
        
        limits = {
            "monthly_minute_limit": 1000,
            "max_concurrent_calls": 1,
            "billing_status": "active"
        }
        if limits_res.data:
            limits = {
                "monthly_minute_limit": limits_res.data[0].get("monthly_minute_limit") or 1000,
                "max_concurrent_calls": limits_res.data[0].get("max_concurrent_calls") or 1,
                "billing_status": limits_res.data[0].get("billing_status") or "active"
            }
            
        # 2. Reconcile workspace limits using owner's hub subscription
        # Get owner ID
        ws_res = db.table("workspaces").select("owner_id").eq("id", workspace_id).execute()
        owner_id = ws_res.data[0].get("owner_id") if ws_res.data else None
        
        owner_email = None
        if owner_id:
            profile_res = db.table("profiles").select("email").eq("id", owner_id).execute()
            owner_email = profile_res.data[0].get("email") if profile_res.data else None
            
        plan_name = "Free Tier"
        if owner_email:
            sub_res = db.table("hub_subscriptions").select("plan, expires_at, subscription_status").eq("email", owner_email).execute()
            if sub_res.data:
                sub = sub_res.data[0]
                expires_at = sub.get("expires_at")
                status = sub.get("subscription_status") or "active"
                is_active = status == "active"
                if is_active and expires_at:
                    try:
                        import dateutil.parser
                        from datetime import datetime, timezone
                        expires_dt = dateutil.parser.isoparse(expires_at)
                        if expires_dt.tzinfo is None:
                            expires_dt = expires_dt.replace(tzinfo=timezone.utc)
                        if expires_dt < datetime.now(timezone.utc):
                            is_active = False
                    except Exception:
                        pass
                if is_active:
                    plan_name = sub.get("plan") or "Free Tier"
                    
        # If paid plan, auto-upgrade limits in limits dict and database
        if plan_name not in ("Free Tier", "Free", "No active plan"):
            # Set default paid limits
            if any(k in plan_name for k in ("Max", "Ecosystem", "Enterprise")):
                expected_minutes = 10000
                expected_concurrency = 5
            else:
                expected_minutes = 5000
                expected_concurrency = 3
                
            if limits["monthly_minute_limit"] < expected_minutes:
                limits["monthly_minute_limit"] = expected_minutes
                limits["max_concurrent_calls"] = expected_concurrency
                try:
                    db.table("workspace_limits").upsert({
                        "workspace_id": workspace_id,
                        "monthly_minute_limit": expected_minutes,
                        "max_concurrent_calls": expected_concurrency,
                        "billing_status": "active"
                    }).execute()
                except Exception as upsert_err:
                    logger.warning(f"Failed to upsert workspace_limits: {upsert_err}")
        else:
            plan_name = "Free Tier" if limits["monthly_minute_limit"] <= 1000 else "Growth Plan"

        # 3. Fetch current month usage counter
        import datetime
        current_month = datetime.datetime.now().strftime("%Y-%m")
        
        usage_res = db.table("workspace_usage_counters").select("used_minutes, estimated_cost").eq("workspace_id", workspace_id).eq("billing_month", current_month).execute()
        
        used_minutes = 0.0
        estimated_cost = 0.0
        if usage_res.data:
            used_minutes = float(usage_res.data[0].get("used_minutes") or 0.0)
            estimated_cost = float(usage_res.data[0].get("estimated_cost") or 0.0)
            
        remaining_minutes = max(0.0, float(limits["monthly_minute_limit"]) - used_minutes)
        
        return {
            "plan_name": plan_name,
            "monthly_minute_limit": limits["monthly_minute_limit"],
            "used_minutes": round(used_minutes, 2),
            "remaining_minutes": round(remaining_minutes, 2),
            "billing_status": limits["billing_status"],
            "estimated_cost": round(estimated_cost, 2),
            "concurrency_limit": limits["max_concurrent_calls"]
        }
    except Exception as e:
        logger.error(f"[get_billing] ERROR: {e}")
        raise HTTPException(status_code=500, detail=str(e))


