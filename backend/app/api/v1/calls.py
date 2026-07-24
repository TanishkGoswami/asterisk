from fastapi import APIRouter, Depends, HTTPException, Request
from typing import Dict, Any
from app.db.client import get_db, Client
from app.core.config import settings
from app.services.telephony_service import TelephonyService
import logging
import subprocess
import shlex

router = APIRouter()
logger = logging.getLogger(__name__)


def execute_asterisk_cli(asterisk_cmd: str) -> Dict[str, Any]:
    """
    Executes an Asterisk CLI command using the unified CLI executor.
    """
    from app.services.asterisk_cli import execute_asterisk_cli_cmd
    return execute_asterisk_cli_cmd(asterisk_cmd)


def is_audiosocket_listening() -> bool:
    """Checks if a TCP listener is active on 127.0.0.1:9092."""
    import socket
    try:
        with socket.create_connection(("127.0.0.1", 9092), timeout=1.0) as s:
            return True
    except Exception:
        return False


def _get_telephony() -> TelephonyService:
    if settings.telephony_provider == "telnyx":
        if not settings.telnyx_api_key or not settings.telnyx_account_sid:
            raise HTTPException(status_code=503, detail="Telnyx credentials not configured")
        return TelephonyService(
            account_sid=settings.telnyx_account_sid,
            auth_token_or_api_key=settings.telnyx_api_key,
            provider="telnyx"
        )
    
    if not settings.twilio_account_sid or not settings.twilio_auth_token:
        raise HTTPException(status_code=503, detail="Twilio credentials not configured")
    return TelephonyService(
        account_sid=settings.twilio_account_sid,
        auth_token_or_api_key=settings.twilio_auth_token,
        provider="twilio"
    )


@router.get("/{workspace_id}/calls")
async def list_calls(workspace_id: str, db: Client = Depends(get_db)):
    result = db.table("calls").select("*").eq("workspace_id", workspace_id).order("created_at", desc=True).execute()
    return result.data


@router.get("/{workspace_id}/calls/{call_id}")
async def get_call(workspace_id: str, call_id: str, db: Client = Depends(get_db)):
    call_result = db.table("calls").select("*").eq("workspace_id", workspace_id).eq("id", call_id).execute()
    if not call_result.data:
        raise HTTPException(status_code=404, detail="Call not found")
    messages_result = db.table("call_messages").select("*").eq("call_id", call_id).order("sequence_number").execute()
    call_data = call_result.data[0]
    call_data["transcript"] = messages_result.data
    
    # Fetch detailed call usage breakdown if exists
    try:
        usage_result = db.table("call_usage").select("*").eq("call_id", call_id).execute()
        if usage_result.data:
            call_data["usage"] = usage_result.data[0]
        else:
            call_data["usage"] = None
    except Exception as e:
        logger.warning(f"Failed to fetch call_usage for call {call_id}: {e}")
        call_data["usage"] = None
        
    return call_data



def end_asterisk_call(call_id: str) -> bool:
    """Terminates an active Asterisk call by locating its channel and requesting a hangup."""
    import subprocess
    import os
    
    # 1. Fetch active channels
    cmd = ["asterisk", "-rx", "core show channels"]
    stdout = ""
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if res.returncode == 0:
            stdout = res.stdout
        else:
            raise FileNotFoundError()
    except (FileNotFoundError, subprocess.SubprocessError):
        # Run via SSH fallback
        ssh_host = os.getenv("ASTERISK_SSH_HOST") or "72.60.202.148"
        ssh_user = os.getenv("ASTERISK_SSH_USER") or "root"
        ssh_cmd = [
            "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
            f"{ssh_user}@{ssh_host}",
            "asterisk -rx \"core show channels\""
        ]
        try:
            ssh_res = subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=12)
            if ssh_res.returncode == 0:
                stdout = ssh_res.stdout
        except Exception as e:
            logger.error(f"[Asterisk End Call] Failed to query remote channels: {e}")
            return False

    if not stdout:
        return False

    # 2. Search for the channel associated with the call_id (UUID)
    channel_name = None
    for line in stdout.splitlines():
        if call_id in line:
            parts = line.split()
            if parts:
                channel_name = parts[0]
                break

    if not channel_name:
        logger.warning(f"[Asterisk End Call] No active channel found for call_id: {call_id}")
        return False

    # 3. Request hangup for the channel
    logger.info(f"[Asterisk End Call] Found channel {channel_name} for call {call_id}. Requesting hangup...")
    hangup_cmd = ["asterisk", "-rx", f"channel request hangup {channel_name}"]
    try:
        res = subprocess.run(hangup_cmd, capture_output=True, text=True, timeout=10)
        if res.returncode == 0:
            return True
        else:
            raise FileNotFoundError()
    except (FileNotFoundError, subprocess.SubprocessError):
        ssh_host = os.getenv("ASTERISK_SSH_HOST") or "72.60.202.148"
        ssh_user = os.getenv("ASTERISK_SSH_USER") or "root"
        ssh_cmd = [
            "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
            f"{ssh_user}@{ssh_host}",
            f"asterisk -rx \"channel request hangup {channel_name}\""
        ]
        try:
            ssh_res = subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=12)
            if ssh_res.returncode == 0:
                return True
        except Exception as e:
            logger.error(f"[Asterisk End Call] Failed to send remote hangup command: {e}")
            
    return False


@router.post("/{workspace_id}/calls/{call_id}/end")
async def end_active_call(
    workspace_id: str,
    call_id: str,
    db: Client = Depends(get_db),
):
    """Programmatically terminate an active call."""
    from app.services.call_admission_control import release_call_reservation
    release_call_reservation(call_id)

    call_result = db.table("calls").select("id, twilio_call_sid, status, provider").eq("workspace_id", workspace_id).eq("id", call_id).execute()
    if not call_result.data:
        raise HTTPException(status_code=404, detail="Call not found")
    
    call_data = call_result.data[0]
    call_sid = call_data.get("twilio_call_sid")
    current_status = call_data.get("status")
    provider = call_data.get("provider")
    
    from datetime import datetime, timezone
    now_iso = datetime.now(timezone.utc).isoformat()
    
    if current_status in ("completed", "failed", "no_answer", "canceled", "busy"):
        return {"status": "already_terminated"}
    
    if provider == "asterisk":
        hangup_success = False
        try:
            hangup_success = end_asterisk_call(call_id)
        except Exception as e:
            logger.error(f"Failed to end Asterisk call: {e}")
            
        try:
            db.table("calls").update({
                "status": "completed",
                "ended_at": now_iso
            }).eq("id", call_id).execute()
        except Exception as db_err:
            logger.error(f"Failed to update call completed status in DB: {db_err}")
            
        return {"status": "terminated" if hangup_success else "terminated_db_only"}
    
    if not call_sid or call_sid == "pending":
        try:
            db.table("calls").update({
                "status": "canceled",
                "ended_at": now_iso
            }).eq("id", call_id).execute()
        except Exception as db_err:
            logger.error(f"Failed to cancel pending call in DB: {db_err}")
        return {"status": "canceled"}
    
    telephony = _get_telephony()
    try:
        telephony.end_call(call_sid)
    except Exception as e:
        logger.error(f"Failed to end call via telephony provider: {e}")
    
    try:
        db.table("calls").update({
            "status": "completed",
            "ended_at": now_iso
        }).eq("id", call_id).execute()
    except Exception as db_err:
        logger.error(f"Failed to update call completed status in DB: {db_err}")
    
    return {"status": "terminated"}


from app.utils.auth import verify_workspace_access

@router.post("/{workspace_id}/agents/{agent_id}/test-call", dependencies=[Depends(verify_workspace_access)])
async def test_call(
    workspace_id: str,
    agent_id: str,
    body: Dict[str, Any],
    request: Request,
    db: Client = Depends(get_db),
):
    """Place an outbound test call to verify an agent's telephony integration."""
    to_number: str = body.get("to_number", "").strip()
    if not to_number:
        raise HTTPException(status_code=400, detail="to_number is required")
        
    # Ensure to_number starts with '+' to conform to E.164 preflight safety regex
    if not to_number.startswith("+"):
        to_number = "+" + to_number

    dry_run = body.get("dry_run", False)
    # Default to True if not provided, since the frontend triggers test calls via explicit button clicks
    confirm_real_dialing = body.get("confirm_real_dialing", True)

    if not dry_run and not confirm_real_dialing:
        raise HTTPException(status_code=400, detail="real_dialing_confirmation_required")

    # Verify agent exists in this workspace
    agent_result = db.table("agents").select("id, name").eq("id", agent_id).eq("workspace_id", workspace_id).execute()
    if not agent_result.data:
        raise HTTPException(status_code=404, detail="Agent not found")

    # Check if the agent has a DID number with provider 'asterisk'
    did_res = db.table("did_numbers").select("id, phone_number, provider, sip_trunk_provider_id").eq("agent_id", agent_id).eq("status", "active").execute()
    
    use_asterisk = False
    from_number = None
    did_number_id = None   # FK to did_numbers table
    trunk_id = None
    
    if did_res.data:
        for did in did_res.data:
            if did.get("provider") == "asterisk":
                use_asterisk = True
                from_number = did.get("phone_number")
                did_number_id = did.get("id")
                trunk_id = did.get("sip_trunk_provider_id")
                break

    if not use_asterisk:
        has_telephony = False
        try:
            if settings.telephony_provider == "telnyx":
                has_telephony = bool(settings.telnyx_api_key and settings.telnyx_account_sid)
            else:
                has_telephony = bool(settings.twilio_account_sid and settings.twilio_auth_token)
        except Exception:
            pass
            
        if not has_telephony and settings.asterisk_audiosocket_enabled:
            trunks_res = db.table("sip_trunk_providers").select("id").eq("workspace_id", workspace_id).execute()
            if trunks_res.data:
                use_asterisk = True
                trunk_id = trunks_res.data[0]["id"]
                if did_res.data:
                    # Use the first DID regardless of provider for caller ID
                    from_number = did_res.data[0].get("phone_number")
                    did_number_id = did_res.data[0].get("id")
                else:
                    # Fallback: look up phone_numbers (NOT a did_numbers FK, so don't set did_number_id)
                    phone_res = db.table("phone_numbers").select("id, phone_number").eq("agent_id", agent_id).eq("status", "active").execute()
                    if phone_res.data:
                        from_number = phone_res.data[0].get("phone_number")

    import uuid
    call_id = str(uuid.uuid4())

    # Preflight safety checks (runs before CAC or reservation)
    from app.services.outbound_safety_service import verify_outbound_dial_safety
    safety = await verify_outbound_dial_safety(
        workspace_id=workspace_id,
        agent_id=agent_id,
        phone_number=to_number,
        call_uuid=call_id,
        dry_run=dry_run
    )
    if not safety.allowed:
        raise HTTPException(status_code=403, detail=f"Dial blocked by safety: {safety.human_readable_reason}")

    if dry_run:
        # Dry-run mode bypasses reservation/origination and returns immediately
        return {
            "status": "dry_run_passed",
            "call_uuid": call_id,
            "message": "Dry-run safety validation passed successfully. No call was placed."
        }

    if use_asterisk:
        if not trunk_id:
            trunks_res = db.table("sip_trunk_providers").select("id").eq("workspace_id", workspace_id).execute()
            if not trunks_res.data:
                raise HTTPException(status_code=400, detail="No active SIP Trunk provider found for Asterisk test call")
            trunk_id = trunks_res.data[0]["id"]
            
        # Call Admission Control reservation
        from app.services.call_admission_control import check_and_reserve_call, release_call_reservation
        
        call_uuid = call_id
        
        allowed, reason = await check_and_reserve_call(
            call_uuid=call_uuid,
            direction="outbound",
            workspace_id=str(workspace_id),
            agent_id=str(agent_id),
            sip_trunk_provider_id=str(trunk_id),
            did_number_id=str(did_number_id) if did_number_id else None,
            caller_id=from_number,
            dialed_number=to_number
        )

        if not allowed:
            try:
                db.table("calls").insert({
                    "id": call_uuid,
                    "call_uuid": call_uuid,
                    "twilio_call_sid": call_uuid,
                    "workspace_id": workspace_id,
                    "agent_id": agent_id,
                    "caller_phone_number": from_number or "unknown",
                    "caller_id": from_number or "unknown",
                    "dialed_number": to_number,
                    "direction": "outbound",
                    "status": "failed",
                    "provider": "asterisk",
                    "metadata": {"provider": "asterisk", "is_test": True, "rejection_reason": reason}
                }).execute()
            except Exception as db_err:
                logger.error(f"[Asterisk Test Call] Failed to insert rejected call record: {db_err}")
            raise HTTPException(status_code=403, detail=f"Call rejected by admission control: {reason or 'internal_error'}")

        # Register call in memory
        from app.services.call_session_manager import call_session_manager
        call_session_manager.register_inbound_asterisk_call(
            call_uuid=call_id,
            caller_id=from_number,
            dialed_number=to_number,
            workspace_id=str(workspace_id),
            agent_id=str(agent_id),
            phone_number_id=str(did_number_id) if did_number_id else ""
        )
        
        # Insert call record in DB
        call_record = {
            "id": call_id,
            "call_uuid": call_id,
            "twilio_call_sid": call_id,
            "workspace_id": workspace_id,
            "agent_id": agent_id,
            "caller_phone_number": from_number or "unknown",
            "caller_id": from_number or "unknown",
            "dialed_number": to_number,
            "direction": "outbound",
            "status": "ringing",
            "provider": "asterisk",
            "sip_trunk_provider_id": trunk_id,
            "metadata": {"provider": "asterisk", "is_test": True}
        }
        # Only set did_number_id if we have a real FK reference to did_numbers
        if did_number_id:
            call_record["did_number_id"] = did_number_id
        try:
            db.table("calls").insert(call_record).execute()
            logger.info(f"[Asterisk Test Call] Registered outbound call record {call_id} in DB")
        except Exception as db_err:
            logger.error(f"[Asterisk Test Call] Failed to write call record to DB: {db_err}")
            release_call_reservation(call_id)
            raise HTTPException(status_code=500, detail=f"Database write failure: {db_err}")
            
        # Format dial number
        dial_number = to_number.strip()
        
        # Query trunk provider type to verify if it is Twilio
        try:
            trunk_res = db.table("sip_trunk_providers").select("provider_type").eq("id", trunk_id).execute()
            provider_type = trunk_res.data[0]["provider_type"] if trunk_res.data else "custom"
        except Exception:
            provider_type = "custom"
            
        if provider_type != "twilio":
            if dial_number.startswith('+'):
                if dial_number.startswith('+91'):
                    dial_number = dial_number[1:]
                    
        # Ensure dial_number has '+' prefix
        if not dial_number.startswith('+'):
            dial_number = '+' + dial_number
                
        endpoint_name = f"provider-{trunk_id}"
        caller_id = from_number or "+18166536732"

        originate_cmd_str = f"asterisk -rx 'channel originate Local/{caller_id}*{trunk_id}*{dial_number}@outbound-local/n application AudioSocket {call_id},127.0.0.1:9092'"

        call_originated = False

        try:
            # Check if Asterisk mode is explicitly 'local'
            if settings.asterisk_mode == "local":
                # 1. Preemptive validation: AudioSocket listening
                if not is_audiosocket_listening():
                    raise HTTPException(
                        status_code=503,
                        detail="AudioSocket server is not listening on 127.0.0.1:9092. Please make sure the local backend is running."
                    )
                    
                # 2. Preemptive validation: PJSIP endpoint existence
                from app.services.asterisk_cli import verify_endpoint_status
                validation = verify_endpoint_status(endpoint_name)
                if validation["status"] == "missing":
                    raise HTTPException(
                        status_code=400,
                        detail=validation["message"]
                    )
                elif validation["status"] in ("unavailable", "cli_error"):
                    raise HTTPException(
                        status_code=502,
                        detail=f"Asterisk connection issue: {validation['message']}"
                    )
                    
                # 3. Execute local originate command directly (no SSH fallback, return errors)
                originate_cmd = f"channel originate Local/{caller_id}*{trunk_id}*{dial_number}@outbound-local/n application AudioSocket {call_id},127.0.0.1:9092"
                res = execute_asterisk_cli(originate_cmd)
                if res["returncode"] != 0:
                    raise HTTPException(
                        status_code=500,
                        detail=f"Asterisk local originate failed (code {res['returncode']}): {res['stderr'] or res['stdout']}. Command run: {res['full_cmd']}"
                    )
                call_originated = True

            else:
                # Non-local mode: try VPS HTTP API → SSH → manual fallback
                import httpx
                # Ensure dial_number has '+' if non-local mode expects it
                if not dial_number.startswith('+'):
                    dial_number = '+' + dial_number
                
                # Strategy 1: Call the VPS backend HTTP API (most reliable from Windows dev machine)
                vps_api_url = (settings.asterisk_vps_url or "").rstrip("/")
                if vps_api_url:
                    try:
                        async with httpx.AsyncClient(timeout=10.0) as client:
                            vps_resp = await client.post(
                                 f"{vps_api_url}/api/calls/asterisk/outbound",
                                 json={
                                     "to_number": dial_number,
                                     "from_number": from_number or "",
                                     "workspace_id": workspace_id,
                                     "agent_id": agent_id,
                                     "call_id": call_id,
                                     "trunk_id": trunk_id,
                                 }
                            )
                            if vps_resp.status_code == 200:
                                call_originated = True
                                resp_data = vps_resp.json()
                                logger.info(f"[Asterisk Test Call] VPS HTTP API originate succeeded: {resp_data}")
                                
                                vps_call_uuid = resp_data.get("call_uuid")
                                vps_db_call_id = resp_data.get("call_id")
                                
                                if vps_call_uuid and vps_call_uuid != call_id:
                                    logger.info(f"[Asterisk Test Call] VPS returned different call_uuid: {vps_call_uuid}. Aligning local session.")
                                    
                                    from app.services.call_session_manager import call_session_manager
                                    call_session_manager.cleanup_call(call_id)
                                    
                                    call_session_manager.register_inbound_asterisk_call(
                                        call_uuid=vps_call_uuid,
                                        caller_id=from_number,
                                        dialed_number=to_number,
                                        workspace_id=str(workspace_id),
                                        agent_id=str(agent_id),
                                        phone_number_id=str(did_number_id) if did_number_id else ""
                                    )
                                    
                                    try:
                                        db.table("calls").delete().eq("id", call_id).execute()
                                        logger.info(f"[Asterisk Test Call] Deleted duplicate local call record: {call_id}")
                                    except Exception as cleanup_err:
                                        logger.warning(f"[Asterisk Test Call] Failed to clean up duplicate local call record: {cleanup_err}")
                                        
                                    if vps_db_call_id:
                                        call_id = vps_db_call_id
                            else:
                                logger.warning(f"[Asterisk Test Call] VPS HTTP API returned {vps_resp.status_code}: {vps_resp.text}")
                    except Exception as http_err:
                        logger.warning(f"[Asterisk Test Call] VPS HTTP API failed: {http_err}")

                # Strategy 2: SSH into VPS and run the command (preferred fallback on Windows)
                if not call_originated:
                    ssh_host = settings.asterisk_ssh_host
                    ssh_user = settings.asterisk_ssh_user
                    ssh_key = settings.asterisk_ssh_key_path or ""
                    ssh_cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5"]
                    if ssh_key:
                        ssh_cmd += ["-i", ssh_key]
                    ssh_cmd += [
                        f"{ssh_user}@{ssh_host}",
                        f"asterisk -rx 'channel originate Local/{caller_id}*{trunk_id}*{dial_number}@outbound-local/n application AudioSocket {call_id},127.0.0.1:9092'"
                    ]
                    try:
                        # Increased timeout to 60 seconds to accommodate network/routing latency
                        ssh_res = subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=60)
                        if ssh_res.returncode == 0:
                            call_originated = True
                            logger.info("[Asterisk Test Call] SSH originate succeeded")
                        else:
                            logger.warning(f"[Asterisk Test Call] SSH originate failed: {ssh_res.stderr}")
                    except Exception as ssh_err:
                        logger.warning(f"[Asterisk Test Call] SSH failed: {ssh_err}")

                # Strategy 3: Run asterisk locally (only if not on Windows or as last resort local fallback)
                if not call_originated:
                    import platform
                    if platform.system() == "Windows":
                        orig_cmd = f"channel originate Local/{caller_id}*{trunk_id}*{dial_number}@outbound-local/n application AudioSocket {call_id},127.0.0.1:9092"
                        cmd = ["wsl", "-u", "root", "bash", "-c", f"asterisk -rx {shlex.quote(orig_cmd)}"]
                    else:
                        cmd = ["asterisk", "-rx", f"channel originate Local/{caller_id}*{trunk_id}*{dial_number}@outbound-local/n application AudioSocket {call_id},127.0.0.1:9092"]
                    try:
                        # Increased timeout to 60 seconds to accommodate slow WSL start/execution latency
                        res = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
                        if res.returncode == 0:
                            call_originated = True
                            logger.info("[Asterisk Test Call] Local/WSL originate succeeded")
                        else:
                            logger.warning(f"[Asterisk Test Call] Local/WSL originate failed: {res.stderr}")
                    except (FileNotFoundError, subprocess.SubprocessError) as err:
                        logger.warning(f"[Asterisk Test Call] Local/WSL originate execution failed: {err}")

        except Exception as orig_err:
            logger.error(f"[Asterisk Test Call] Originate execution threw exception: {orig_err}", exc_info=True)
            release_call_reservation(call_id)
            try:
                db.table("calls").update({"status": "failed", "rejection_reason": str(orig_err)}).eq("id", call_id).execute()
            except Exception:
                pass
            raise HTTPException(status_code=500, detail=f"Originate failed: {str(orig_err)}")

        if not call_originated:
            # Rollback reservation since call won't start automatically
            release_call_reservation(call_id)
            try:
                db.table("calls").update({"status": "failed", "rejection_reason": "manual_required"}).eq("id", call_id).execute()
            except Exception:
                pass
            border = "=" * 80
            logger.info(f"\n{border}\n[MANUAL ACTION REQUIRED] All automatic originate methods failed.\n"
                        f"Run this command directly in your VPS terminal:\n\n"
                        f"  {originate_cmd_str}\n{border}\n")
            return {
                "status": "manual_required",
                "call_sid": call_id,
                "to": to_number,
                "call_id": call_id,
                "message": "Run the originate command in your VPS terminal to start the call.",
                "command": originate_cmd_str
            }
                
        return {"status": "calling", "call_sid": call_id, "to": to_number, "call_id": call_id}

    # Standard Twilio/Telnyx route fallback
    telephony = _get_telephony()

    # Determine the from_ number: env var → first number on account
    if settings.telephony_provider == "telnyx":
        from_number = settings.telnyx_phone_number or telephony.get_first_phone_number()
    else:
        from_number = settings.twilio_phone_number or telephony.get_first_phone_number()

    if not from_number:
        provider_name = settings.telephony_provider.capitalize()
        raise HTTPException(
            status_code=503,
            detail=f"No {provider_name} phone number available. Add {provider_name.upper()}_PHONE_NUMBER to your .env."
        )

    # Resolve the public base URL dynamically from request headers
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    host = request.headers.get("x-forwarded-host") or request.url.netloc
    
    # If accessed via localhost/127.0.0.1, fallback to configured base URL / webhook base URL
    if ("localhost" in host or "127.0.0.1" in host):
        if settings.public_base_url:
            webhook_base = settings.public_base_url.rstrip("/")
        else:
            if settings.telephony_provider == "telnyx":
                webhook_base = (settings.telnyx_webhook_url or "").rstrip("/").removesuffix("/api/webhooks/telnyx/inbound").removesuffix("/api/webhook/telnyx/inbound")
            else:
                webhook_base = (settings.twilio_webhook_url or "").rstrip("/").removesuffix("/api/webhooks/twilio/inbound").removesuffix("/api/webhook/twilio/inbound")
    else:
        webhook_base = f"{proto}://{host}"

    if settings.telephony_provider == "telnyx":
        texml_url = f"{webhook_base}/api/webhooks/telnyx/test-call?agent_id={agent_id}&call_db_id={call_id}"
        status_callback_url = f"{webhook_base}/api/webhooks/telnyx/status"
    else:
        texml_url = f"{webhook_base}/api/webhooks/twilio/test-call?agent_id={agent_id}&call_db_id={call_id}"
        status_callback_url = f"{webhook_base}/api/webhooks/twilio/status"

    # Log the call in DB first with our pre-generated call_id to prevent webhook race conditions
    pn_result = db.table("phone_numbers").select("id").eq("phone_number", from_number).execute()
    pn_id = pn_result.data[0]["id"] if pn_result.data else None

    db.table("calls").insert({
        "id": call_id,
        "workspace_id": workspace_id,
        "agent_id": agent_id,
        "phone_number_id": pn_id,
        "caller_phone_number": to_number,
        "twilio_call_sid": f"pending-{call_id}",  # will be updated with actual SID below
        "direction": "outbound",
        "status": "ringing",
        "metadata": {"is_test": True, "provider": settings.telephony_provider}
    }).execute()

    try:
        call_sid = telephony.make_outbound_call(
            to=to_number,
            from_=from_number,
            texml_url=texml_url,
            status_callback_url=status_callback_url,
        )

        # Update call record with real Twilio/Telnyx CallSid
        db.table("calls").update({
            "twilio_call_sid": call_sid
        }).eq("id", call_id).execute()

    except Exception as e:
        logger.error(f"Test call failed: {e}", exc_info=True)
        # Update status to failed
        try:
            db.table("calls").update({"status": "failed"}).eq("id", call_id).execute()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=str(e))

    return {"status": "calling", "call_sid": call_sid, "to": to_number, "call_id": call_id}


asterisk_router = APIRouter()

@asterisk_router.post("/api/calls/asterisk/outbound")
async def asterisk_outbound_call(body: Dict[str, Any], db: Client = Depends(get_db)):
    """
    Outbound SIP Trunk route for Asterisk. Originate a call via PJSIP/AudioSocket.
    Accepts an optional call_id and trunk_id when called from the test-call endpoint
    (so the UUID stays consistent between the registered session and the originate command).
    """
    to_number = body.get("to_number", "").strip()
    from_number = body.get("from_number", "").strip()
    workspace_id = body.get("workspace_id", "").strip()
    agent_id = body.get("agent_id", "").strip()
    # Optional: pre-generated call_id and trunk_id from the calling backend
    provided_call_id = body.get("call_id", "").strip()
    provided_trunk_id = body.get("trunk_id", "").strip()

    if not to_number or not workspace_id or not agent_id:
        raise HTTPException(
            status_code=400,
            detail="Missing required body fields: to_number, workspace_id, agent_id"
        )

    # Validate agent exists and is tied to the workspace
    agent_result = db.table("agents").select("id").eq("id", agent_id).eq("workspace_id", workspace_id).execute()
    if not agent_result.data:
        raise HTTPException(status_code=404, detail="Agent not found in specified workspace")

    trunk_id = provided_trunk_id or None

    # Find DID and trunk if not provided
    if from_number:
        did_res = db.table("did_numbers").select("id, sip_trunk_provider_id").eq("phone_number", from_number).execute()
        phone_id = None

        if did_res.data:
            phone_id = did_res.data[0]["id"]
            if not trunk_id:
                trunk_id = did_res.data[0].get("sip_trunk_provider_id")
        else:
            phone_res = db.table("phone_numbers").select("id").eq("phone_number", from_number).execute()
            if phone_res.data:
                phone_id = phone_res.data[0]["id"]
    else:
        phone_id = None
        did_res = type("obj", (object,), {"data": []})()

    if not trunk_id:
        trunks_res = db.table("sip_trunk_providers").select("id").eq("workspace_id", workspace_id).execute()
        if not trunks_res.data:
            raise HTTPException(status_code=400, detail=f"No active SIP Trunk provider found in workspace {workspace_id}")
        trunk_id = trunks_res.data[0]["id"]

    # --- Lowest-level Hard Safety Guard ---
    from app.services.outbound_safety_service import get_kill_switch_enabled
    outbound_calls_enabled = get_kill_switch_enabled("OUTBOUND_CALLS_ENABLED")
    real_dialing_enabled = get_kill_switch_enabled("REAL_DIALING_ENABLED")
    
    if not outbound_calls_enabled or not real_dialing_enabled:
        raise HTTPException(
            status_code=403,
            detail="Dial blocked: Outbound dialing globally blocked by lowest-level safety guard"
        )
        
    if not provided_call_id:
        raise HTTPException(
            status_code=400,
            detail="Dial blocked: Outbound dialing requires a pre-generated call_id/call_uuid reservation"
        )
        
    # Verify active reservation
    from app.services.call_admission_control import redis_client
    reservation_active = False
    if settings.allow_calls_without_redis:
        reservation_active = True
    else:
        if redis_client:
            try:
                reservation_active = bool(redis_client.get(f"call:{provided_call_id}:reservation"))
            except Exception:
                pass
                
        if not reservation_active:
            res_db = db.table("call_reservations").select("status").eq("call_uuid", provided_call_id).eq("status", "reserved").execute()
            if res_db.data:
                reservation_active = True
            
    if not reservation_active:
        raise HTTPException(
            status_code=403,
            detail="Dial blocked: No active call reservation found for this call_uuid"
        )
        
    # Verify trunk status is enabled
    trunk_db = db.table("sip_trunk_providers").select("status").eq("id", trunk_id).execute()
    if not trunk_db.data or trunk_db.data[0].get("status") == "disabled":
        raise HTTPException(
            status_code=403,
            detail="Dial blocked: SIP trunk provider is disabled"
        )
        
    # Verify campaign/item states if batch call
    batch_run_id = body.get("batch_run_id")
    batch_item_id = body.get("batch_item_id")
    if batch_run_id:
        run_res = db.table("batch_call_runs").select("status").eq("id", batch_run_id).execute()
        if not run_res.data or run_res.data[0].get("status") != "running":
            raise HTTPException(
                status_code=403,
                detail="Dial blocked: Campaign run is not active/running"
            )
    if batch_item_id:
        item_res = db.table("batch_call_items").select("status").eq("id", batch_item_id).execute()
        if not item_res.data or item_res.data[0].get("status") != "dialing":
            raise HTTPException(
                status_code=403,
                detail="Dial blocked: Campaign lead status is not dialing"
            )
    # --- End Hard Guard ---

    import uuid
    import os

    # Reuse call_id if provided (avoids UUID mismatch with registered call session)
    if provided_call_id:
        call_uuid = provided_call_id
        db_call_id = provided_call_id
        # Only skip DB insert if the caller is not a batch campaign (which does not pre-insert records)
        skip_db_insert = not bool(body.get("batch_run_id"))
    else:
        db_call_id = str(uuid.uuid4())
        call_uuid = str(uuid.uuid4())
        skip_db_insert = False

    # Check if this call was already reserved in Redis (e.g. by test_call route)
    already_reserved = False
    from app.services.call_admission_control import redis_client
    if redis_client:
        try:
            already_reserved = bool(redis_client.get(f"call:{call_uuid}:reservation"))
        except Exception:
            pass

    if not already_reserved:
        from app.services.call_admission_control import check_and_reserve_call
        allowed, reason = await check_and_reserve_call(
            call_uuid=call_uuid,
            direction="outbound",
            workspace_id=str(workspace_id),
            agent_id=str(agent_id),
            sip_trunk_provider_id=str(trunk_id) if trunk_id else None,
            did_number_id=str(phone_id) if phone_id else None,
            caller_id=from_number,
            dialed_number=to_number
        )

        if not allowed:
            if not skip_db_insert:
                try:
                    db.table("calls").insert({
                        "id": db_call_id,
                        "call_uuid": call_uuid,
                        "twilio_call_sid": call_uuid,
                        "workspace_id": workspace_id,
                        "agent_id": agent_id,
                        "caller_phone_number": from_number or "unknown",
                        "caller_id": from_number or "unknown",
                        "dialed_number": to_number,
                        "direction": "outbound",
                        "status": "failed",
                        "rejection_reason": reason or "internal_error",
                        "provider": "asterisk",
                        "metadata": {"provider": "asterisk"}
                    }).execute()
                except Exception as e:
                    logger.error(f"[Asterisk Outbound] Failed to insert rejected call record: {e}")
            raise HTTPException(status_code=403, detail=f"Call rejected by admission control: {reason or 'internal_error'}")

    if not skip_db_insert:
        # Pre-register call details in CallSessionManager in-memory cache
        from app.services.call_session_manager import call_session_manager
        call_session_manager.register_inbound_asterisk_call(
            call_uuid=call_uuid,
            caller_id=from_number or "unknown",
            dialed_number=to_number,
            workspace_id=str(workspace_id),
            agent_id=str(agent_id),
            phone_number_id=str(phone_id) if phone_id else ""
        )

        from datetime import datetime, timezone
        call_record = {
            "id": db_call_id,
            "call_uuid": call_uuid,
            "twilio_call_sid": call_uuid,
            "workspace_id": workspace_id,
            "agent_id": agent_id,
            "caller_phone_number": from_number or "unknown",
            "caller_id": from_number or "unknown",
            "dialed_number": to_number,
            "direction": "outbound",
            "status": "ringing",
            "provider": "asterisk",
            "sip_trunk_provider_id": trunk_id,
            "metadata": {"provider": "asterisk"}
        }
        if phone_id and did_res.data:
            call_record["did_number_id"] = phone_id
        try:
            db.table("calls").insert(call_record).execute()
            logger.info(f"[Asterisk Outbound] Registered outbound call record {call_uuid} in DB")
        except Exception as db_err:
            logger.error(f"[Asterisk Outbound] Failed to write call record to DB: {db_err}")
            from app.services.call_admission_control import release_call_reservation
            release_call_reservation(call_uuid)
            raise HTTPException(status_code=500, detail=f"Database write failure: {db_err}")

    # Format dial number
    dial_number = to_number.strip()
    
    # Query trunk provider type to verify if it is Twilio
    try:
        trunk_res = db.table("sip_trunk_providers").select("provider_type").eq("id", trunk_id).execute()
        provider_type = trunk_res.data[0]["provider_type"] if trunk_res.data else "custom"
    except Exception:
        provider_type = "custom"
        
    if provider_type != "twilio":
        if dial_number.startswith('+'):
            if dial_number.startswith('+91'):
                dial_number = dial_number[1:]
                
    # Ensure dial_number has '+' prefix
    if not dial_number.startswith('+'):
        dial_number = '+' + dial_number
            
    endpoint_name = f"provider-{trunk_id}"
    caller_id = from_number or "+18166536732"

    orig_cmd = f"channel originate Local/{caller_id}*{trunk_id}*{dial_number}@outbound-local/n application AudioSocket {call_uuid},127.0.0.1:9092"

    call_originated = False

    try:
        if settings.asterisk_mode == "local":
            # 1. AudioSocket listening validation
            if not is_audiosocket_listening():
                raise HTTPException(
                    status_code=503,
                    detail="AudioSocket server is not listening on 127.0.0.1:9092. Please make sure the local backend is running."
                )
                
            # 2. Endpoint validation
            endpoint_check = execute_asterisk_cli(f"pjsip show endpoint {endpoint_name}")
            if endpoint_check["returncode"] != 0 or "Unable to find" in endpoint_check["stdout"] or "not found" in endpoint_check["stdout"].lower():
                raise HTTPException(
                    status_code=400,
                    detail=f"SIP Trunk Endpoint '{endpoint_name}' does not exist in Asterisk. Please check your pjsip.conf configuration."
                )
                
            # 3. Execute local originate command directly
            res = execute_asterisk_cli(orig_cmd)
            if res["returncode"] != 0:
                raise HTTPException(
                    status_code=500,
                    detail=f"Asterisk local originate failed (code {res['returncode']}): {res['stderr'] or res['stdout']}. Command run: {res['full_cmd']}"
                )
            call_originated = True
        else:
            # Non-local mode (traditional VPS / Production mode with fallback logic)
            if not dial_number.startswith('+'):
                dial_number = '+' + dial_number
            
            # Execute using execute_asterisk_cli (which handles local/SSH configuration automatically)
            res = execute_asterisk_cli(orig_cmd)
            if res["returncode"] == 0:
                call_originated = True

    except Exception as orig_err:
        logger.error(f"[Asterisk Outbound] Originate command execution failed: {orig_err}", exc_info=True)
        from app.services.outbound_safety_service import record_circuit_failure
        record_circuit_failure("originate")
        if "sip trunk" in str(orig_err).lower() or "endpoint" in str(orig_err).lower():
            record_circuit_failure("trunk")
        
        from app.services.call_admission_control import release_call_reservation
        release_call_reservation(call_uuid)
        try:
            db.table("calls").update({"status": "failed", "rejection_reason": str(orig_err)}).eq("id", db_call_id).execute()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=str(orig_err))

    if not call_originated:
        from app.services.outbound_safety_service import record_circuit_failure
        record_circuit_failure("originate")
        
        from app.services.call_admission_control import release_call_reservation
        release_call_reservation(call_uuid)
        try:
            db.table("calls").update({"status": "failed", "rejection_reason": "manual_required"}).eq("id", db_call_id).execute()
        except Exception:
            pass
        # Fallback manual instructions
        border = "=" * 80
        originate_cmd_str = f"asterisk -rx '{orig_cmd}'"
        logger.info(f"\n{border}\n[MANUAL ACTION REQUIRED] Outbound originate failed.\n"
                    f"Run this command directly in your VPS terminal:\n\n"
                    f"  {originate_cmd_str}\n{border}\n")
        return {
            "status": "manual_required",
            "call_uuid": call_uuid,
            "call_id": db_call_id,
            "message": "Run the originate command in your VPS terminal.",
            "command": originate_cmd_str
        }

    return {"status": "calling", "call_uuid": call_uuid, "call_id": db_call_id}


@asterisk_router.get("/api/v1/telephony/asterisk/diagnostics")
async def asterisk_diagnostics():
    import socket
    
    detected_errors = []
    
    # 1. Check AudioSocket 9092
    audiosocket_listening = False
    try:
        with socket.create_connection(("127.0.0.1", 9092), timeout=1.0) as s:
            audiosocket_listening = True
    except Exception as e:
        detected_errors.append(f"AudioSocket not listening on 9092: {e}")
        
    # 2. Check Asterisk CLI Execution
    can_execute = False
    asterisk_version = "Unknown"
    asterisk_running = False
    pjsip_endpoints = ""
    pjsip_registrations = ""
    
    version_res = execute_asterisk_cli("core show version")
    if version_res["returncode"] == 0:
        can_execute = True
        asterisk_running = True
        asterisk_version = version_res["stdout"].strip()
    else:
        detected_errors.append(f"CLI execution failed (code {version_res['returncode']}): {version_res['stderr']}")
        
    # If running, query endpoints and registrations
    if asterisk_running:
        endpoints_res = execute_asterisk_cli("pjsip show endpoints")
        if endpoints_res["returncode"] == 0:
            pjsip_endpoints = endpoints_res["stdout"]
        else:
            detected_errors.append(f"Failed to query endpoints: {endpoints_res['stderr']}")
            
        regs_res = execute_asterisk_cli("pjsip show registrations")
        if regs_res["returncode"] == 0:
            pjsip_registrations = regs_res["stdout"]
        else:
            detected_errors.append(f"Failed to query registrations: {regs_res['stderr']}")
            
    return {
        "asterisk_running": asterisk_running,
        "asterisk_version": asterisk_version,
        "pjsip_registrations": pjsip_registrations,
        "pjsip_endpoints": pjsip_endpoints,
        "audiosocket_listening_9092": audiosocket_listening,
        "can_execute_asterisk_cli": can_execute,
        "current_env_mode": settings.asterisk_mode,
        "detected_errors": detected_errors
    }


@asterisk_router.post("/api/v1/telephony/test-local-originate")
async def test_local_originate(payload: Dict[str, Any]):
    dest = payload.get("destination_number", "").strip()
    provider = payload.get("provider_endpoint", "").strip()
    caller = payload.get("caller_id", "").strip() or "+18166536732"
    
    if not dest or not provider:
        raise HTTPException(status_code=400, detail="Missing destination_number or provider_endpoint")
        
    import uuid
    call_uuid = str(uuid.uuid4())
    
    # Check format compatibility
    dial_number = dest
    provider_type = "custom"
    if provider.startswith("provider-"):
        t_id = provider.replace("provider-", "")
        # Query db to get provider_type
        try:
            trunk_res = db.table("sip_trunk_providers").select("provider_type").eq("id", t_id).execute()
            if trunk_res.data:
                provider_type = trunk_res.data[0]["provider_type"]
        except Exception:
            pass

    t_id = provider.replace("provider-", "") if provider.startswith("provider-") else provider
    orig_cmd = f"channel originate Local/{caller}*{t_id}*{dial_number}@outbound-local/n application AudioSocket {call_uuid},127.0.0.1:9092"

    
    # Execute command
    res = execute_asterisk_cli(orig_cmd)
    
    return {
        "status": "success" if res["returncode"] == 0 else "failed",
        "returncode": res["returncode"],
        "stdout": res["stdout"],
        "stderr": res["stderr"],
        "command_run": res["full_cmd"],
        "execution_method": res["execution_method"]
    }

