import logging
import jwt
import base64
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.core.config import settings
from app.db.client import get_db, Client

logger = logging.getLogger(__name__)
security = HTTPBearer()

async def get_current_user_id(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> str:
    """
    Decodes the Supabase JWT and returns the user's ID.
    """
    token = credentials.credentials
    payload = None

    # Tier 1: Try verifying using JWKS (for asymmetric verification)
    try:
        from jwt import PyJWKClient
        jwks_url = f"{settings.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"
        headers = {
            "apikey": settings.supabase_anon_key,
            "Authorization": f"Bearer {settings.supabase_anon_key}"
        }
        jwks_client = PyJWKClient(jwks_url, headers=headers)
        signing_key = jwks_client.get_signing_key_from_jwt(token)
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["HS256", "RS256", "ES256"],
            options={"verify_aud": False}
        )
    except Exception as jwks_err:
        logger.warning(f"[auth] JWKS verification failed or skipped: {jwks_err}. Falling back to symmetric secret...")

    # Tier 2: Fallback to symmetric HS256 secret (supabase_jwt_secret)
    if not payload:
        try:
            try:
                secret = base64.b64decode(settings.supabase_jwt_secret)
            except Exception:
                secret = settings.supabase_jwt_secret

            payload = jwt.decode(
                token,
                secret,
                algorithms=["HS256"],
                options={"verify_aud": False}
            )
        except jwt.ExpiredSignatureError:
            raise HTTPException(status_code=401, detail="Token has expired")
        except jwt.InvalidTokenError as e:
            logger.error(f"[auth] Symmetric verification failed: {e}")
            raise HTTPException(status_code=401, detail=f"Invalid token: {str(e)}")

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token: missing subject claim")
    return user_id

async def verify_workspace_access(
    workspace_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Client = Depends(get_db)
) -> None:
    """
    Enforces that the user has access to the workspace (is owner or member).
    """
    try:
        # Check if user is owner of the workspace
        ws_res = db.table("workspaces").select("id").eq("id", workspace_id).eq("owner_id", user_id).execute()
        if ws_res.data:
            return

        # Check if user is a member of the workspace
        member_res = db.table("workspace_members").select("id").eq("workspace_id", workspace_id).eq("user_id", user_id).execute()
        if member_res.data:
            return

        raise HTTPException(status_code=403, detail="Forbidden: You do not have access to this workspace")
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        logger.error(f"[auth] Failed to verify workspace access: {e}")
        raise HTTPException(status_code=500, detail="Internal server error verifying workspace access")
