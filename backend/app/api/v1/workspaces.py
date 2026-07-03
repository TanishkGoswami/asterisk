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
