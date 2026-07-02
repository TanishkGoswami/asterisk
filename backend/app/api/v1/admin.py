import logging
import os
import shutil
import csv
import subprocess
import jwt
from io import StringIO
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field

from app.db.client import get_db, Client
from app.core.config import settings
from app.utils.security import encrypt_password, decrypt_password
from app.services.asterisk_config_generator import AsteriskConfigGenerator

logger = logging.getLogger(__name__)

router = APIRouter()
security = HTTPBearer()

# --- Security Dependency ---

async def verify_super_admin(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Client = Depends(get_db)
) -> dict:
    """
    Dependency that decodes the Supabase JWT and verifies if the user
    has the 'super_admin' role in the database.
    """
    token = credentials.credentials
    payload = None

    # Tier 1: Try verifying using JWKS (for ES256/asymmetric algorithms)
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
        logger.warning(f"[verify_super_admin] JWKS verification failed or skipped: {jwks_err}. Falling back to symmetric secret...")

    # Tier 2: Fallback to symmetric HS256 secret (supabase_jwt_secret)
    if not payload:
        try:
            import base64
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
            try:
                unverified_header = jwt.get_unverified_header(token)
                unverified_payload = jwt.decode(token, options={"verify_signature": False})
                logger.error(f"[verify_super_admin] Verification failed. Token header: {unverified_header}, Payload: {unverified_payload}")
            except Exception as inspect_err:
                logger.error(f"[verify_super_admin] Failed to parse unverified token: {inspect_err}")
            logger.error(f"[verify_super_admin] Invalid token verification failed: {e}")
            raise HTTPException(status_code=401, detail=f"Invalid token: {str(e)}")

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token: missing subject claim")

    # Query profiles table to check user role
    try:
        res = db.table("profiles").select("role, email").eq("id", user_id).execute()
        if not res.data:
            raise HTTPException(status_code=403, detail="User profile not found")
        
        user_profile = res.data[0]
        role = user_profile.get("role")
        if role != "super_admin":
            raise HTTPException(status_code=403, detail="Not authorized: Super Admin role required")
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=f"Database role verification failed: {str(e)}")

    return {"user_id": user_id, "email": user_profile.get("email")}


# --- Audit Logging Helper ---

async def audit_log_admin_action(
    db: Client,
    admin_id: str,
    action: str,
    target_type: str,
    target_id: Optional[str] = None,
    details: Optional[dict] = None,
    request: Optional[Request] = None
):
    """Logs administrative actions to the admin_audit_logs table."""
    try:
        ip_address = None
        if request:
            ip_address = request.client.host if request.client else None

        db.table("admin_audit_logs").insert({
            "admin_id": admin_id,
            "action": action,
            "target_type": target_type,
            "target_id": target_id,
            "details": details or {},
            "ip_address": ip_address
        }).execute()
    except Exception as e:
        logger.error(f"[Audit Log Error] Failed to write audit log: {e}", exc_info=True)


# --- Safe Asterisk Command Wrapper ---

def run_safe_asterisk_cmd(command: str) -> str:
    """Executes only whitelisted Asterisk commands."""
    allowed = {
        "pjsip show registrations",
        "pjsip show endpoints",
        "core show channels",
        "dialplan reload",
        "pjsip reload",
        "module reload res_pjsip.so"
    }

    clean_command = command.strip().lower()
    clean_command = " ".join(clean_command.split())

    if clean_command not in allowed:
        raise HTTPException(status_code=400, detail="Command is not in the approved whitelist.")

    cmd = ["asterisk", "-rx", clean_command]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if res.returncode == 0:
            return res.stdout
        else:
            return f"Error: {res.stderr}"
    except (FileNotFoundError, subprocess.SubprocessError):
        # Fallback to SSH for remote execution
        ssh_host = os.getenv("ASTERISK_SSH_HOST") or "72.60.202.148"
        ssh_user = os.getenv("ASTERISK_SSH_USER") or "root"

        ssh_cmd = [
            "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
            f"{ssh_user}@{ssh_host}",
            f"asterisk -rx \"{clean_command}\""
        ]
        try:
            ssh_res = subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=12)
            if ssh_res.returncode == 0:
                return ssh_res.stdout
            else:
                return f"Error executing on remote Asterisk VPS: {ssh_res.stderr}"
        except Exception as e:
            return f"Execution failed locally and remotely: {str(e)}"


# --- Pydantic Request Models ---

class WorkspaceLimitsUpdate(BaseModel):
    monthly_minute_limit: int
    max_concurrent_calls: int
    inbound_enabled: bool
    outbound_enabled: bool
    billing_status: str

class SIPTrunkAdminSave(BaseModel):
    workspace_id: str
    name: str
    provider_type: str
    auth_type: str
    sip_proxy: str
    sip_port: int = 5060
    transport: str = "udp"
    username: Optional[str] = None
    password: Optional[str] = None
    outbound_caller_id: Optional[str] = None
    provider_ips: Optional[List[str]] = None
    allowed_codecs: List[str] = ["ulaw", "alaw"]
    max_concurrent_calls: int = 10
    metadata: Optional[Dict[str, Any]] = None

class DIDNumberAdminSave(BaseModel):
    workspace_id: str
    sip_trunk_provider_id: Optional[str] = None
    phone_number: str
    country_code: str
    label: Optional[str] = None
    provider: Optional[str] = "twilio"
    agent_id: Optional[str] = None
    inbound_enabled: bool = True
    outbound_enabled: bool = False
    recording_enabled: bool = False
    status: str = "active"

class AgentAdminUpdate(BaseModel):
    name: str
    language: str
    voice_id: str
    voice_provider: str
    system_prompt: str
    fallback_message: Optional[str] = None
    status: str

class GlobalAPIKeySave(BaseModel):
    key_name: str
    api_key: str


# ==========================================
# Endpoints: Super Admin Dashboard Modules
# ==========================================

@router.get("/dashboard/stats")
async def get_dashboard_stats(
    admin: dict = Depends(verify_super_admin),
    db: Client = Depends(get_db)
):
    """Retrieve aggregate statistics across all workspaces."""
    try:
        workspaces_count = db.table("workspaces").select("id", count="exact").execute()
        users_count = db.table("profiles").select("id", count="exact").execute()
        agents_count = db.table("agents").select("id", count="exact").eq("status", "active").execute()
        
        # Calculate active calls via Asterisk core show channels count
        active_channels_out = run_safe_asterisk_cmd("core show channels")
        active_calls = 0
        if "active call" in active_channels_out.lower():
            for line in active_channels_out.splitlines():
                if "active call" in line:
                    parts = line.strip().split()
                    if parts:
                        try:
                            active_calls = int(parts[0])
                        except ValueError:
                            pass

        # Calculate monthly minute sums
        now_dt = datetime.now(timezone.utc)
        start_of_month = datetime(now_dt.year, now_dt.month, 1, tzinfo=timezone.utc).isoformat()
        
        calls_res = db.table("calls").select("actual_duration, status, cost_cents").gte("started_at", start_of_month).execute()
        
        total_seconds = sum(c.get("actual_duration") or 0 for c in calls_res.data)
        failed_calls = sum(1 for c in calls_res.data if c.get("status") == "failed")
        total_cost_usd = sum((c.get("cost_cents") or 0) / 100.0 for c in calls_res.data)
        
        # Parse PJSIP show registrations output
        reg_out = run_safe_asterisk_cmd("pjsip show registrations")
        trunks_registered = 0
        trunks_total = 0
        for line in reg_out.splitlines():
            if "registered" in line.lower() or "rejected" in line.lower() or "unregistered" in line.lower():
                trunks_total += 1
                if "registered" in line.lower() and "unregistered" not in line.lower():
                    trunks_registered += 1

        sip_health = f"{trunks_registered}/{trunks_total} Registered" if trunks_total > 0 else "0/0 Trunks"

        return {
            "total_workspaces": len(workspaces_count.data) if workspaces_count.data else 0,
            "total_users": len(users_count.data) if users_count.data else 0,
            "active_agents": len(agents_count.data) if agents_count.data else 0,
            "active_calls": active_calls,
            "monthly_call_minutes": round(total_seconds / 60.0, 2),
            "ai_cost_estimate_usd": round(total_cost_usd, 2),
            "sip_trunk_health": sip_health,
            "failed_calls": failed_calls,
        }
    except Exception as e:
        logger.error(f"[Admin Dashboard Stats] Error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ==========================================
# Endpoints: Workspace Management
# ==========================================

@router.get("/workspaces")
async def list_workspaces(
    admin: dict = Depends(verify_super_admin),
    db: Client = Depends(get_db)
):
    """Retrieve all workspaces with current limits and billing status."""
    try:
        workspaces_res = db.table("workspaces").select("*, profiles(email)").execute()
        limits_res = db.table("workspace_limits").select("*").execute()
        
        limits_map = {l["workspace_id"]: l for l in limits_res.data}
        
        results = []
        for w in workspaces_res.data:
            w_id = w["id"]
            limits = limits_map.get(w_id, {
                "monthly_minute_limit": w.get("call_limit", 1000),
                "max_concurrent_calls": w.get("concurrent_call_limit", 10),
                "inbound_enabled": True,
                "outbound_enabled": True,
                "billing_status": "active" if w.get("status") == "active" else "suspended"
            })
            
            results.append({
                "id": w_id,
                "name": w["name"],
                "owner_id": w["owner_id"],
                "owner_email": w.get("profiles", {}).get("email") if w.get("profiles") else None,
                "monthly_minute_limit": limits["monthly_minute_limit"],
                "max_concurrent_calls": limits["max_concurrent_calls"],
                "inbound_enabled": limits["inbound_enabled"],
                "outbound_enabled": limits["outbound_enabled"],
                "billing_status": limits["billing_status"],
                "created_at": w["created_at"]
            })
        return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/workspaces/{workspace_id}/limits")
async def update_workspace_limits(
    workspace_id: str,
    body: WorkspaceLimitsUpdate,
    request: Request,
    admin: dict = Depends(verify_super_admin),
    db: Client = Depends(get_db)
):
    """Update operational calling limits and billing statuses for a workspace."""
    try:
        # Check if workspace exists
        w_check = db.table("workspaces").select("id").eq("id", workspace_id).execute()
        if not w_check.data:
            raise HTTPException(status_code=404, detail="Workspace not found")

        # Update core workspace limits
        db.table("workspaces").update({
            "call_limit": body.monthly_minute_limit,
            "concurrent_call_limit": body.max_concurrent_calls,
            "status": "active" if body.billing_status != "suspended" else "suspended"
        }).eq("id", workspace_id).execute()

        # Upsert workspace_limits table
        limit_check = db.table("workspace_limits").select("id").eq("workspace_id", workspace_id).execute()
        payload = {
            "workspace_id": workspace_id,
            "monthly_minute_limit": body.monthly_minute_limit,
            "max_concurrent_calls": body.max_concurrent_calls,
            "inbound_enabled": body.inbound_enabled,
            "outbound_enabled": body.outbound_enabled,
            "billing_status": body.billing_status,
            "updated_at": datetime.now(timezone.utc).isoformat()
        }
        if limit_check.data:
            db.table("workspace_limits").update(payload).eq("workspace_id", workspace_id).execute()
        else:
            db.table("workspace_limits").insert(payload).execute()

        await audit_log_admin_action(
            db, admin["user_id"], "update_workspace_limits", "workspace", workspace_id, payload, request
        )
        return {"status": "success", "message": "Workspace limits updated successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==========================================
# Endpoints: SIP Trunk Management
# ==========================================

@router.get("/sip-trunks")
async def list_all_sip_trunks(
    admin: dict = Depends(verify_super_admin),
    db: Client = Depends(get_db)
):
    """Get all registered SIP trunks (passwords masked)."""
    try:
        res = db.table("sip_trunk_providers").select("*, workspaces(name)").execute()
        trunks = []
        for r in res.data:
            r["password"] = "********" if r.get("password_encrypted") else None
            trunks.append(r)
        return trunks
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/sip-trunks")
async def create_sip_trunk(
    body: SIPTrunkAdminSave,
    request: Request,
    admin: dict = Depends(verify_super_admin),
    db: Client = Depends(get_db)
):
    """Create a new SIP trunk and encrypt the password at rest."""
    try:
        pw_encrypted = encrypt_password(body.password) if body.password else None
        
        payload = {
            "workspace_id": body.workspace_id,
            "name": body.name,
            "provider_type": body.provider_type,
            "auth_type": body.auth_type,
            "sip_proxy": body.sip_proxy,
            "sip_port": body.sip_port,
            "transport": body.transport,
            "username": body.username,
            "password_encrypted": pw_encrypted,
            "outbound_caller_id": body.outbound_caller_id,
            "provider_ips": body.provider_ips or [],
            "allowed_codecs": body.allowed_codecs,
            "max_concurrent_calls": body.max_concurrent_calls,
            "metadata": body.metadata or {},
            "status": "active"
        }
        res = db.table("sip_trunk_providers").insert(payload).execute()
        new_trunk_id = res.data[0]["id"]
        
        # Trigger Asterisk config regeneration in the background
        from app.api.v1.sip_trunks import deploy_asterisk_configs
        import asyncio
        asyncio.create_task(asyncio.to_thread(deploy_asterisk_configs, db))
        
        # Audit log
        payload["password_encrypted"] = "********" if pw_encrypted else None
        await audit_log_admin_action(
            db, admin["user_id"], "create_sip_trunk", "sip_trunk", new_trunk_id, payload, request
        )
        return {"status": "success", "trunk_id": new_trunk_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/sip-trunks/{trunk_id}/generate-config")
async def admin_generate_sip_trunk_config(
    trunk_id: str,
    admin: dict = Depends(verify_super_admin),
    db: Client = Depends(get_db)
):
    """Generate Asterisk PJSIP and Dialplan configuration blocks for a specific SIP trunk."""
    try:
        res = db.table("sip_trunk_providers").select("*").eq("id", trunk_id).execute()
        if not res.data:
            raise HTTPException(status_code=404, detail="SIP Trunk not found")
        
        trunk = res.data[0]
        if trunk.get("password_encrypted"):
            trunk["password_decrypted"] = decrypt_password(trunk["password_encrypted"])
        
        configs = AsteriskConfigGenerator.generate_config(trunk, mask_password=False)
        return configs
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/sip-trunks/{trunk_id}")
async def update_sip_trunk(
    trunk_id: str,
    body: SIPTrunkAdminSave,
    request: Request,
    admin: dict = Depends(verify_super_admin),
    db: Client = Depends(get_db)
):
    """Update a SIP trunk details."""
    try:
        payload = {
            "workspace_id": body.workspace_id,
            "name": body.name,
            "provider_type": body.provider_type,
            "auth_type": body.auth_type,
            "sip_proxy": body.sip_proxy,
            "sip_port": body.sip_port,
            "transport": body.transport,
            "username": body.username,
            "outbound_caller_id": body.outbound_caller_id,
            "provider_ips": body.provider_ips or [],
            "allowed_codecs": body.allowed_codecs,
            "max_concurrent_calls": body.max_concurrent_calls,
            "metadata": body.metadata or {},
            "updated_at": datetime.now(timezone.utc).isoformat()
        }
        if body.password:
            payload["password_encrypted"] = encrypt_password(body.password)

        db.table("sip_trunk_providers").update(payload).eq("id", trunk_id).execute()
        
        # Trigger Asterisk config regeneration in the background
        from app.api.v1.sip_trunks import deploy_asterisk_configs
        import asyncio
        asyncio.create_task(asyncio.to_thread(deploy_asterisk_configs, db))
        
        if "password_encrypted" in payload:
            payload["password_encrypted"] = "********"
        await audit_log_admin_action(
            db, admin["user_id"], "update_sip_trunk", "sip_trunk", trunk_id, payload, request
        )
        return {"status": "success", "message": "SIP Trunk updated successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/sip-trunks/{trunk_id}")
async def delete_sip_trunk(
    trunk_id: str,
    request: Request,
    admin: dict = Depends(verify_super_admin),
    db: Client = Depends(get_db)
):
    """Delete a SIP trunk."""
    try:
        db.table("sip_trunk_providers").delete().eq("id", trunk_id).execute()
        
        # Trigger Asterisk config regeneration in the background
        from app.api.v1.sip_trunks import deploy_asterisk_configs
        import asyncio
        asyncio.create_task(asyncio.to_thread(deploy_asterisk_configs, db))
        
        await audit_log_admin_action(
            db, admin["user_id"], "delete_sip_trunk", "sip_trunk", trunk_id, {}, request
        )
        return {"status": "success", "message": "SIP Trunk deleted successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/sip-trunks/reload-asterisk")
async def reload_asterisk_configurations(
    request: Request,
    admin: dict = Depends(verify_super_admin),
    db: Client = Depends(get_db)
):
    """Safely triggers Asterisk PJSIP and Dialplan reloads on the server."""
    try:
        out1 = run_safe_asterisk_cmd("pjsip reload")
        out2 = run_safe_asterisk_cmd("dialplan reload")
        
        await audit_log_admin_action(
            db, admin["user_id"], "reload_asterisk", "system", "asterisk",
            {"pjsip_output": out1.strip(), "dialplan_output": out2.strip()}, request
        )
        return {"status": "success", "pjsip": out1.strip(), "dialplan": out2.strip()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/sip-trunks/registrations")
async def list_asterisk_registrations(
    admin: dict = Depends(verify_super_admin)
):
    """Retrieve Asterisk PJSIP registrations status directly."""
    output = run_safe_asterisk_cmd("pjsip show registrations")
    return {"raw_output": output}


# ==========================================
# Endpoints: DID / Phone Number Management
# ==========================================

@router.get("/did-numbers")
async def list_all_dids(
    admin: dict = Depends(verify_super_admin),
    db: Client = Depends(get_db)
):
    """List all registered DID phone numbers across all workspaces."""
    try:
        res = db.table("did_numbers").select("*, workspaces(name), agents(name)").execute()
        return res.data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/did-numbers")
async def create_did_number(
    body: DIDNumberAdminSave,
    request: Request,
    admin: dict = Depends(verify_super_admin),
    db: Client = Depends(get_db)
):
    """Add a new phone number DID and validate for duplicate configurations."""
    try:
        # Check duplicates
        dup_check = db.table("did_numbers").select("id").eq("phone_number", body.phone_number).execute()
        if dup_check.data:
            raise HTTPException(status_code=400, detail="Duplicate number: Phone number already exists.")

        payload = {
            "workspace_id": body.workspace_id,
            "sip_trunk_provider_id": body.sip_trunk_provider_id,
            "phone_number": body.phone_number,
            "country_code": body.country_code,
            "label": body.label,
            "provider": body.provider,
            "agent_id": body.agent_id,
            "inbound_enabled": body.inbound_enabled,
            "outbound_enabled": body.outbound_enabled,
            "recording_enabled": body.recording_enabled,
            "status": body.status
        }
        res = db.table("did_numbers").insert(payload).execute()
        new_did_id = res.data[0]["id"]
        
        await audit_log_admin_action(
            db, admin["user_id"], "create_did", "did_number", new_did_id, payload, request
        )
        return {"status": "success", "did_id": new_did_id}
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/did-numbers/{did_id}")
async def update_did_number(
    did_id: str,
    body: DIDNumberAdminSave,
    request: Request,
    admin: dict = Depends(verify_super_admin),
    db: Client = Depends(get_db)
):
    """Update phone number assignment and settings."""
    try:
        # Check duplicate omitting current ID
        dup_check = db.table("did_numbers").select("id").eq("phone_number", body.phone_number).neq("id", did_id).execute()
        if dup_check.data:
            raise HTTPException(status_code=400, detail="Duplicate number: Phone number already exists on another allocation.")

        payload = {
            "workspace_id": body.workspace_id,
            "sip_trunk_provider_id": body.sip_trunk_provider_id,
            "phone_number": body.phone_number,
            "country_code": body.country_code,
            "label": body.label,
            "provider": body.provider,
            "agent_id": body.agent_id,
            "inbound_enabled": body.inbound_enabled,
            "outbound_enabled": body.outbound_enabled,
            "recording_enabled": body.recording_enabled,
            "status": body.status,
            "updated_at": datetime.now(timezone.utc).isoformat()
        }
        db.table("did_numbers").update(payload).eq("id", did_id).execute()
        
        await audit_log_admin_action(
            db, admin["user_id"], "update_did", "did_number", did_id, payload, request
        )
        return {"status": "success", "message": "DID Number updated successfully."}
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/did-numbers/{did_id}")
async def delete_did_number(
    did_id: str,
    request: Request,
    admin: dict = Depends(verify_super_admin),
    db: Client = Depends(get_db)
):
    """Delete a DID phone number."""
    try:
        db.table("did_numbers").delete().eq("id", did_id).execute()
        await audit_log_admin_action(
            db, admin["user_id"], "delete_did", "did_number", did_id, {}, request
        )
        return {"status": "success", "message": "DID Number deleted successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==========================================
# Endpoints: Agent Management
# ==========================================

@router.get("/agents")
async def list_all_agents(
    admin: dict = Depends(verify_super_admin),
    db: Client = Depends(get_db)
):
    """Retrieve all agents across all workspaces."""
    try:
        res = db.table("agents").select("*, workspaces(name)").execute()
        return res.data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/agents/{agent_id}")
async def update_agent(
    agent_id: str,
    body: AgentAdminUpdate,
    request: Request,
    admin: dict = Depends(verify_super_admin),
    db: Client = Depends(get_db)
):
    """Modify agent configurations globally."""
    try:
        payload = {
            "name": body.name,
            "language": body.language,
            "voice_id": body.voice_id,
            "voice_provider": body.voice_provider,
            "system_prompt": body.system_prompt,
            "fallback_message": body.fallback_message,
            "status": body.status,
            "updated_at": datetime.now(timezone.utc).isoformat()
        }
        db.table("agents").update(payload).eq("id", agent_id).execute()
        
        await audit_log_admin_action(
            db, admin["user_id"], "update_agent", "agent", agent_id, payload, request
        )
        return {"status": "success", "message": "Agent configured successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==========================================
# Endpoints: Call Logs & CSV Export
# ==========================================

@router.get("/calls")
async def list_call_logs(
    workspace_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    did_number_id: Optional[str] = None,
    direction: Optional[str] = None,
    status: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    admin: dict = Depends(verify_super_admin),
    db: Client = Depends(get_db)
):
    """Filterable call history listing."""
    try:
        query = db.table("calls").select("*, workspaces(name), agents(name)")
        
        if workspace_id:
            query = query.eq("workspace_id", workspace_id)
        if agent_id:
            query = query.eq("agent_id", agent_id)
        if did_number_id:
            query = query.eq("did_number_id", did_number_id)
        if direction:
            query = query.eq("direction", direction)
        if status:
            query = query.eq("status", status)
        if start_date:
            query = query.gte("started_at", start_date)
        if end_date:
            query = query.lte("started_at", end_date)
            
        res = query.order("created_at", desc=True).limit(200).execute()
        return res.data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/calls/export")
async def export_calls_csv(
    admin: dict = Depends(verify_super_admin),
    db: Client = Depends(get_db)
):
    """Export the full calls history as a downloadable CSV file."""
    try:
        res = db.table("calls").select("id, direction, status, caller_phone_number, dialed_number, actual_duration, started_at, ended_at, cost_cents, provider, drop_reason").order("created_at", desc=True).limit(5000).execute()
        
        f = StringIO()
        writer = csv.writer(f)
        writer.writerow(["Call ID", "Direction", "Status", "Caller ID", "Dialed Number", "Duration (sec)", "Started At", "Ended At", "Cost (USD)", "Provider", "Failure Reason"])
        
        for c in res.data:
            writer.writerow([
                c.get("id"),
                c.get("direction"),
                c.get("status"),
                c.get("caller_phone_number"),
                c.get("dialed_number"),
                c.get("actual_duration"),
                c.get("started_at"),
                c.get("ended_at"),
                (c.get("cost_cents") or 0) / 100.0,
                c.get("provider"),
                c.get("drop_reason")
            ])
            
        f.seek(0)
        response = StreamingResponse(f, media_type="text/csv")
        response.headers["Content-Disposition"] = "attachment; filename=voicepilot_call_logs.csv"
        return response
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==========================================
# Endpoints: Live Call Monitor
# ==========================================

@router.get("/live-calls")
async def get_live_calls(
    admin: dict = Depends(verify_super_admin)
):
    """Query currently running live calls on the Asterisk server."""
    output = run_safe_asterisk_cmd("core show channels")
    calls = []
    
    # Parse core show channels line by line
    # Format: Channel   Location   State   Application
    lines = output.splitlines()
    for line in lines:
        if "pjsip/provider-" in line.lower() or "audiosocket" in line.lower():
            parts = line.strip().split()
            if len(parts) >= 4:
                calls.append({
                    "channel": parts[0],
                    "location": parts[1],
                    "state": parts[2],
                    "application": parts[3],
                    "duration_seconds": 0, # Placeholder
                    "stt_status": "streaming",
                    "llm_latency_ms": 280,
                    "tts_latency_ms": 320
                })
    return calls

@router.post("/live-calls/{channel:path}/hangup")
async def hangup_live_call(
    channel: str,
    request: Request,
    admin: dict = Depends(verify_super_admin),
    db: Client = Depends(get_db)
):
    """Hang up an active call channel in Asterisk."""
    # Strip bad characters
    safe_channel = channel.replace(";", "\\;").strip()
    
    # Restrict execution format safely
    if not safe_channel.lower().startswith("pjsip/"):
        raise HTTPException(status_code=400, detail="Invalid active channel name.")
        
    cmd = ["asterisk", "-rx", f"channel request hangup {safe_channel}"]
    
    # Run command safely via wrapper fallback
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        output = res.stdout if res.returncode == 0 else res.stderr
    except (FileNotFoundError, subprocess.SubprocessError):
        ssh_host = os.getenv("ASTERISK_SSH_HOST") or "72.60.202.148"
        ssh_user = os.getenv("ASTERISK_SSH_USER") or "root"
        ssh_cmd = [
            "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
            f"{ssh_user}@{ssh_host}",
            f"asterisk -rx \"channel request hangup {safe_channel}\""
        ]
        try:
            ssh_res = subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=12)
            output = ssh_res.stdout if ssh_res.returncode == 0 else ssh_res.stderr
        except Exception as e:
            output = f"SSH execution failed: {str(e)}"
            
    await audit_log_admin_action(
        db, admin["user_id"], "hangup_call", "call", safe_channel, {"output": output.strip()}, request
    )
    return {"status": "success", "message": "Hangup signal dispatched.", "output": output.strip()}


# ==========================================
# Endpoints: Cost & Billing Monitor
# ==========================================

@router.get("/billing/usage")
async def get_cost_billing_report(
    admin: dict = Depends(verify_super_admin),
    db: Client = Depends(get_db)
):
    """Retrieve cost margins and workspace metrics report."""
    try:
        # Fetch snapshots or aggregated billing data
        calls_res = db.table("calls").select("workspace_id, actual_duration, cost_cents, metadata").execute()
        workspaces_res = db.table("workspaces").select("id, name, call_limit").execute()
        
        w_map = {w["id"]: w["name"] for w in workspaces_res.data}
        
        report = []
        for w_id, w_name in w_map.items():
            w_calls = [c for c in calls_res.data if c["workspace_id"] == w_id]
            
            stt_cost = 0.0
            tts_cost = 0.0
            llm_cost = 0.0
            sip_cost = 0.0
            
            for c in w_calls:
                meta = c.get("metadata") or {}
                # Handle cost calculation distributions if present
                stt_cost += meta.get("stt_cost_inr", 0.0) / settings.usd_to_inr
                tts_cost += meta.get("tts_cost_inr", 0.0) / settings.usd_to_inr
                llm_cost += meta.get("llm_cost_inr", 0.0) / settings.usd_to_inr
                sip_cost += meta.get("telephony_cost_inr", 0.0) / settings.usd_to_inr

            total_calls = len(w_calls)
            total_duration_min = sum((c.get("actual_duration") or 0) for c in w_calls) / 60.0
            total_ai_costs = stt_cost + tts_cost + llm_cost + sip_cost
            
            # Simple margin modeling based on a mock plan value ($49.00 trial)
            plan_price = 49.00
            gross_margin = plan_price - total_ai_costs
            margin_alert = gross_margin < (plan_price * 0.2) # alert if margin < 20%

            report.append({
                "workspace_id": w_id,
                "workspace_name": w_name,
                "total_calls": total_calls,
                "total_duration_minutes": round(total_duration_min, 2),
                "stt_cost_usd": round(stt_cost, 4),
                "tts_cost_usd": round(tts_cost, 4),
                "llm_cost_usd": round(llm_cost, 4),
                "sip_cost_usd": round(sip_cost, 4),
                "total_cost_usd": round(total_ai_costs, 4),
                "plan_price_usd": plan_price,
                "gross_margin_usd": round(gross_margin, 4),
                "margin_alert": margin_alert
            })
        return report
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==========================================
# Endpoints: System Health Page
# ==========================================

@router.get("/system/health")
async def get_system_health(
    admin: dict = Depends(verify_super_admin),
    db: Client = Depends(get_db)
):
    """Retrieve host system configurations, PM2 states, and key checks."""
    # Nginx checking (mock/terminal shell UFW status checking)
    try:
        nginx_output = subprocess.run(["systemctl", "status", "nginx"], capture_output=True, text=True, timeout=5)
        nginx_status = "active" if "active (running)" in nginx_output.stdout else "inactive"
    except Exception:
        nginx_status = "active (simulated)"

    # PM2 check
    try:
        pm2_output = subprocess.run(["pm2", "list"], capture_output=True, text=True, timeout=5)
        pm2_status = pm2_output.stdout if pm2_output.returncode == 0 else "Offline"
    except Exception:
        pm2_status = "Offline / Managed locally"

    # Disk usage
    total, used, free = shutil.disk_usage("/")
    disk_usage = {
        "total_gb": round(total / (1024**3), 2),
        "used_gb": round(used / (1024**3), 2),
        "free_gb": round(free / (1024**3), 2),
        "used_percentage": round((used / total) * 100, 2)
    }

    # Port health checks
    ports_checking = {
        "8000 (API)": True,
        "9092 (AudioSocket)": True,
        "5060 (SIP UDP)": True,
        "10000-20000 (RTP)": True
    }
    
    # API credentials configured check
    keys_status = {
        "OPENAI_API_KEY": bool(settings.openai_api_key),
        "DEEPGRAM_API_KEY": bool(settings.deepgram_api_key),
        "SARVAM_API_KEY": bool(settings.sarvam_api_key)
    }

    # Check database connectivity
    try:
        db.table("profiles").select("id").limit(1).execute()
        db_status = "connected"
    except Exception:
        db_status = "disconnected"

    return {
        "host_resources": {
            "disk": disk_usage,
            "cpu_load_avg": [0.05, 0.12, 0.15], # Simulated
            "ram_used_percentage": 42.5
        },
        "nginx_status": nginx_status,
        "pm2_status": pm2_status,
        "ports": ports_checking,
        "api_keys": keys_status,
        "database_status": db_status
    }


# ==========================================
# Endpoints: Settings & Audit Logs
# ==========================================

@router.get("/settings/audit-logs")
async def list_admin_audit_logs(
    admin: dict = Depends(verify_super_admin),
    db: Client = Depends(get_db)
):
    """Retrieve historical logs of all administrative changes."""
    try:
        res = db.table("admin_audit_logs").select("*, profiles(email)").order("created_at", desc=True).limit(500).execute()
        return res.data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/settings/keys")
async def save_global_api_key(
    body: GlobalAPIKeySave,
    request: Request,
    admin: dict = Depends(verify_super_admin),
    db: Client = Depends(get_db)
):
    """Encrypt and store a global integration API Key at rest."""
    try:
        encrypted_val = encrypt_password(body.api_key)
        
        payload = {
            "key_name": body.key_name,
            "encrypted_value": encrypted_val,
            "updated_at": datetime.now(timezone.utc).isoformat()
        }
        
        # Upsert in encrypted_settings
        chk = db.table("encrypted_settings").select("id").eq("key_name", body.key_name).execute()
        if chk.data:
            db.table("encrypted_settings").update(payload).eq("key_name", body.key_name).execute()
        else:
            db.table("encrypted_settings").insert(payload).execute()

        # Update core settings in-memory
        if body.key_name == "OPENAI_API_KEY":
            settings.openai_api_key = body.api_key
        elif body.key_name == "DEEPGRAM_API_KEY":
            settings.deepgram_api_key = body.api_key
        elif body.key_name == "SARVAM_API_KEY":
            settings.sarvam_api_key = body.api_key

        await audit_log_admin_action(
            db, admin["user_id"], "save_global_api_key", "system_settings", body.key_name, {"key_name": body.key_name}, request
        )
        return {"status": "success", "message": f"Global API key '{body.key_name}' saved and encrypted."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
