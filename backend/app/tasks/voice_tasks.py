import logging
import time
from typing import Any, Dict
from datetime import datetime, timezone as dt_timezone
from app.core.celery_app import celery_app
from app.db.client import get_supabase_client
from app.core.config import settings

logger = logging.getLogger(__name__)

def _get_telephony():
    """Helper to initialize telephony service from config."""
    from app.services.telephony_service import TelephonyService
    if settings.telephony_provider == "telnyx":
        return TelephonyService(
            account_sid=settings.telnyx_account_sid,
            auth_token_or_api_key=settings.telnyx_api_key,
            provider="telnyx"
        )
    return TelephonyService(
        account_sid=settings.twilio_account_sid,
        auth_token_or_api_key=settings.twilio_auth_token,
        provider="twilio"
    )

def _handle_task_completion(db, task_id: str, success: bool):
    """Update task status and handle recurrence logic."""
    from .scheduler import calculate_next_run

    task_res = db.table("scheduled_tasks").select("*").eq("id", task_id).execute()
    if not task_res.data:
        return

    task = task_res.data[0]
    rrule = task.get("recurrence_rule")

    if rrule:
        next_run = calculate_next_run(rrule, datetime.now(dt_timezone.utc))
        if next_run:
            db.table("scheduled_tasks").update({
                "status": "scheduled",
                "next_run_at": next_run.isoformat()
            }).eq("id", task_id).execute()
            return

    final_status = "completed" if success else "failed"
    db.table("scheduled_tasks").update({"status": final_status}).eq("id", task_id).execute()

def run_voice_call(task_id: str, payload: Dict[str, Any], attempt: int = 1):
    """Direct execution logic for a voice call with full telephony integration."""
    db = get_supabase_client()
    start_time = time.time()

    try:
        # 1. Fetch task data
        task_res = db.table("scheduled_tasks").select("*").eq("id", task_id).execute()
        if not task_res.data:
            raise ValueError(f"Task {task_id} not found")
        task = task_res.data[0]

        agent_id = task["agent_id"]
        workspace_id = task["workspace_id"]
        to_number = payload.get("to")

        if not to_number:
            raise ValueError("Recipient phone number ('to') missing in payload")

        # Determine if we should use Asterisk for this call
        did_res = db.table("did_numbers").select("id, phone_number, provider, sip_trunk_provider_id").eq("agent_id", agent_id).eq("status", "active").execute()
        
        use_asterisk = False
        from_number = None
        did_number_id = None
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
                        from_number = did_res.data[0].get("phone_number")
                        did_number_id = did_res.data[0].get("id")
                    else:
                        phone_res = db.table("phone_numbers").select("id, phone_number").eq("agent_id", agent_id).eq("status", "active").execute()
                        if phone_res.data:
                            from_number = phone_res.data[0].get("phone_number")

        import uuid
        call_id = str(uuid.uuid4())

        if use_asterisk:
            if not trunk_id:
                trunks_res = db.table("sip_trunk_providers").select("id").eq("workspace_id", workspace_id).execute()
                if not trunks_res.data:
                    raise ValueError(f"No active SIP Trunk provider found for Asterisk outbound call (agent {agent_id})")
                trunk_id = trunks_res.data[0]["id"]

            # Run CAC reservation synchronously
            from app.services.call_admission_control import check_and_reserve_call, release_call_reservation
            from app.services.call_session_manager import call_session_manager

            # Helper to run async in sync
            def run_async(coro):
                import asyncio
                try:
                    loop = asyncio.get_event_loop()
                except RuntimeError:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                
                if loop.is_running():
                    from concurrent.futures import ThreadPoolExecutor
                    with ThreadPoolExecutor() as executor:
                        return executor.submit(lambda: asyncio.run(coro)).result()
                else:
                    return loop.run_until_complete(coro)

            allowed, reason = run_async(check_and_reserve_call(
                call_uuid=call_id,
                direction="outbound",
                workspace_id=str(workspace_id),
                agent_id=str(agent_id),
                sip_trunk_provider_id=str(trunk_id),
                did_number_id=str(did_number_id) if did_number_id else None,
                caller_id=from_number,
                dialed_number=to_number
            ))

            if not allowed:
                # Insert failed call record
                try:
                    db.table("calls").insert({
                        "id": call_id,
                        "call_uuid": call_id,
                        "twilio_call_sid": call_id,
                        "workspace_id": workspace_id,
                        "agent_id": agent_id,
                        "caller_phone_number": from_number or "unknown",
                        "caller_id": from_number or "unknown",
                        "dialed_number": to_number,
                        "direction": "outbound",
                        "status": "failed",
                        "provider": "asterisk",
                        "metadata": {"provider": "asterisk", "is_scheduled": True, "rejection_reason": reason}
                    }).execute()
                except Exception as db_err:
                    logger.error(f"Failed to insert rejected call record: {db_err}")
                raise ValueError(f"Call rejected by admission control: {reason or 'internal_error'}")

            # Register call in memory
            call_session_manager.register_inbound_asterisk_call(
                call_uuid=call_id,
                caller_id=from_number,
                dialed_number=to_number,
                workspace_id=str(workspace_id),
                agent_id=str(agent_id),
                phone_number_id=str(did_number_id) if did_number_id else ""
            )

            # Insert ringing call record
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
                "metadata": {"provider": "asterisk", "is_scheduled": True}
            }
            if did_number_id:
                call_record["did_number_id"] = did_number_id
            
            try:
                db.table("calls").insert(call_record).execute()
            except Exception as db_err:
                logger.error(f"Failed to write call record to DB: {db_err}")
                release_call_reservation(call_id)
                raise

            # Format dial number
            dial_number = to_number.strip()
            try:
                trunk_res = db.table("sip_trunk_providers").select("provider_type").eq("id", trunk_id).execute()
                provider_type = trunk_res.data[0]["provider_type"] if trunk_res.data else "custom"
            except Exception:
                provider_type = "custom"

            if provider_type != "twilio":
                if dial_number.startswith('+'):
                    if dial_number.startswith('+91'):
                        dial_number = dial_number[1:]

            if not dial_number.startswith('+'):
                dial_number = '+' + dial_number

            endpoint_name = f"provider-{trunk_id}"
            caller_id = from_number or "+18166536732"

            # Prepare originate command execution functions
            from app.api.v1.calls import execute_asterisk_cli, is_audiosocket_listening

            call_originated = False
            originate_error = None

            try:
                if settings.asterisk_mode == "local":
                    if not is_audiosocket_listening():
                        raise ValueError("AudioSocket server is not listening on 127.0.0.1:9092")

                    endpoint_check = execute_asterisk_cli(f"pjsip show endpoint {endpoint_name}")
                    if endpoint_check["returncode"] != 0 or "Unable to find" in endpoint_check["stdout"] or "not found" in endpoint_check["stdout"].lower():
                        raise ValueError(f"SIP Trunk Endpoint '{endpoint_name}' does not exist in Asterisk")

                    orig_cmd = f"channel originate Local/{caller_id}*{trunk_id}*{dial_number}@outbound-local/n application AudioSocket {call_id},127.0.0.1:9092"
                    res = execute_asterisk_cli(orig_cmd)
                    if res["returncode"] != 0:
                        raise ValueError(f"Asterisk local originate failed (code {res['returncode']}): {res['stderr'] or res['stdout']}")
                    call_originated = True
                else:
                    # Strategy 1: VPS HTTP API
                    vps_api_url = (settings.asterisk_vps_url or "").rstrip("/")
                    if vps_api_url:
                        try:
                            import httpx
                            vps_resp = httpx.post(
                                f"{vps_api_url}/api/calls/asterisk/outbound",
                                json={
                                    "to_number": dial_number,
                                    "from_number": from_number or "",
                                    "workspace_id": workspace_id,
                                    "agent_id": agent_id,
                                    "call_id": call_id,
                                    "trunk_id": trunk_id,
                                },
                                timeout=10.0
                            )
                            if vps_resp.status_code == 200:
                                call_originated = True
                                resp_data = vps_resp.json()
                                vps_call_uuid = resp_data.get("call_uuid")
                                if vps_call_uuid and vps_call_uuid != call_id:
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
                                    except Exception:
                                        pass
                                    call_id = vps_call_uuid
                            else:
                                logger.warning(f"VPS HTTP API returned {vps_resp.status_code}: {vps_resp.text}")
                        except Exception as e:
                            logger.warning(f"VPS HTTP API failed: {e}")

                    # Strategy 2: SSH fallback
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
                            import subprocess
                            ssh_res = subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=60)
                            if ssh_res.returncode == 0:
                                call_originated = True
                            else:
                                logger.warning(f"SSH originate failed: {ssh_res.stderr}")
                        except Exception as e:
                            logger.warning(f"SSH failed: {e}")

                    # Strategy 3: Local fallback
                    if not call_originated:
                        import platform
                        import shlex
                        orig_cmd = f"channel originate Local/{caller_id}*{trunk_id}*{dial_number}@outbound-local/n application AudioSocket {call_id},127.0.0.1:9092"
                        if platform.system() == "Windows":
                            cmd = ["wsl", "-u", "root", "bash", "-c", f"asterisk -rx {shlex.quote(orig_cmd)}"]
                        else:
                            cmd = ["asterisk", "-rx", f"channel originate Local/{caller_id}*{trunk_id}*{dial_number}@outbound-local/n application AudioSocket {call_id},127.0.0.1:9092"]
                        try:
                            res = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
                            if res.returncode == 0:
                                call_originated = True
                            else:
                                logger.warning(f"Local fallback originate failed: {res.stderr}")
                        except Exception as e:
                            logger.warning(f"Local fallback originate failed: {e}")

            except Exception as e:
                originate_error = e

            if not call_originated:
                release_call_reservation(call_id)
                try:
                    db.table("calls").update({"status": "failed", "rejection_reason": str(originate_error or "originate_failed")}).eq("id", call_id).execute()
                except Exception:
                    pass
                raise originate_error or ValueError("Outbound originate failed for all strategies")

            # Log task success
            duration = int((time.time() - start_time) * 1000)
            try:
                db.table("scheduled_task_logs").insert({
                    "scheduled_task_id": task_id,
                    "status": "success",
                    "attempt_number": attempt,
                    "duration_ms": duration,
                    "finished_at": datetime.now(dt_timezone.utc).isoformat(),
                    "result": {"call_sid": call_id, "provider": "asterisk"}
                }).execute()
            except Exception as e:
                logger.warning(f"Could not insert success log: {e}")

            try:
                db.table("notifications").insert({
                    "user_id": task["user_id"],
                    "workspace_id": workspace_id,
                    "title": "Task Executed",
                    "message": f"Scheduled Asterisk call '{task['title']}' was triggered successfully.",
                    "type": "task_completed"
                }).execute()
            except Exception as e:
                logger.warning(f"Could not insert notification: {e}")

            _handle_task_completion(db, task_id, True)
            return True

        # 2. Setup Telephony (fallback for Twilio/Telnyx)
        telephony = _get_telephony()

        if settings.public_base_url:
            webhook_base = settings.public_base_url.rstrip("/")
        else:
            if settings.telephony_provider == "telnyx":
                webhook_base = (settings.telnyx_webhook_url or "").rstrip("/").removesuffix("/api/webhooks/telnyx/inbound").removesuffix("/api/webhook/telnyx/inbound")
            else:
                webhook_base = (settings.twilio_webhook_url or "").rstrip("/").removesuffix("/api/webhooks/twilio/inbound").removesuffix("/api/webhook/twilio/inbound")

        if settings.telephony_provider == "telnyx":
            from_number = settings.telnyx_phone_number or telephony.get_first_phone_number()
            texml_url = f"{webhook_base}/api/webhooks/telnyx/test-call?agent_id={agent_id}&workspace_id={workspace_id}"
            status_callback_url = f"{webhook_base}/api/webhooks/telnyx/status"
        else:
            from_number = settings.twilio_phone_number or telephony.get_first_phone_number()
            texml_url = f"{webhook_base}/api/webhooks/twilio/test-call?agent_id={agent_id}&workspace_id={workspace_id}"
            status_callback_url = f"{webhook_base}/api/webhooks/twilio/status"

        if not from_number:
            raise ValueError(f"No phone number available for provider {settings.telephony_provider}")

        # Normalize phone numbers to E.164 (remove spaces, dashes, parens)
        def _normalize(num: str) -> str:
            import re
            return re.sub(r"[\s\-\(\)]", "", num)

        to_number = _normalize(to_number)
        from_number = _normalize(from_number)

        logger.info(f"Triggering outbound call from {from_number} to {to_number} for agent {agent_id}")

        # 3. Place Call
        call_sid = telephony.make_outbound_call(
            to=to_number,
            from_=from_number,
            texml_url=texml_url,
            status_callback_url=status_callback_url,
        )

        # 4. Insert call record after we have the real call_sid
        normalized_from = from_number.replace(" ", "").replace("-", "")
        pn_result = db.table("phone_numbers").select("id").eq("phone_number", normalized_from).execute()
        if not pn_result.data:
            pn_result = db.table("phone_numbers").select("id").eq("phone_number", from_number).execute()
        pn_id = pn_result.data[0]["id"] if pn_result.data else None

        try:
            db.table("calls").insert({
                "workspace_id": workspace_id,
                "agent_id": agent_id,
                "phone_number_id": pn_id,
                "caller_phone_number": to_number,
                "twilio_call_sid": call_sid,
                "direction": "outbound",
                "status": "ringing",
                "metadata": {"is_scheduled": True, "task_id": task_id}
            }).execute()
        except Exception as db_err:
            # Log the DB error but don't fail the task — call was already placed
            logger.warning(f"Could not insert call record for scheduled call {task_id}: {db_err}")

        # 5. Log task success (non-fatal if these DB writes fail)
        duration = int((time.time() - start_time) * 1000)

        try:
            db.table("scheduled_task_logs").insert({
                "scheduled_task_id": task_id,
                "status": "success",
                "attempt_number": attempt,
                "duration_ms": duration,
                "finished_at": datetime.now(dt_timezone.utc).isoformat(),
                "result": {"call_sid": call_sid}
            }).execute()
        except Exception as e:
            logger.warning(f"Could not insert success log for {task_id}: {e}")

        try:
            db.table("notifications").insert({
                "user_id": task["user_id"],
                "workspace_id": workspace_id,
                "title": "Task Executed",
                "message": f"Scheduled call '{task['title']}' was triggered successfully.",
                "type": "task_completed"
            }).execute()
        except Exception as e:
            logger.warning(f"Could not insert notification for {task_id}: {e}")

        _handle_task_completion(db, task_id, True)
        return True

    except Exception as exc:
        logger.error(f"Scheduled call {task_id} failed: {exc}", exc_info=True)

        db.table("scheduled_task_logs").insert({
            "scheduled_task_id": task_id,
            "status": "failed",
            "attempt_number": attempt,
            "error_message": str(exc),
            "finished_at": datetime.now(dt_timezone.utc).isoformat()
        }).execute()

        _handle_task_completion(db, task_id, False)
        return False

def run_webhook(task_id: str, payload: Dict[str, Any], attempt: int = 1):
    """Direct execution logic for a webhook."""
    import httpx
    db = get_supabase_client()
    url = payload.get("url")

    try:
        if not url:
            raise ValueError("Webhook URL missing in payload")

        with httpx.Client() as client:
            resp = client.post(url, json=payload.get("data", {}), timeout=10.0)
            resp.raise_for_status()

        _handle_task_completion(db, task_id, True)
        return True
    except Exception as e:
        logger.error(f"Webhook {task_id} failed: {e}")
        _handle_task_completion(db, task_id, False)
        return False

@celery_app.task(bind=True, max_retries=3)
def execute_voice_call(self, task_id: str, payload: Dict[str, Any]):
    if not run_voice_call(task_id, payload, attempt=self.request.retries + 1):
        raise self.retry(countdown=60 * (self.request.retries + 1))

@celery_app.task(bind=True, max_retries=3)
def execute_webhook(self, task_id: str, payload: Dict[str, Any]):
    if not run_webhook(task_id, payload, attempt=self.request.retries + 1):
        raise self.retry(countdown=60 * (self.request.retries + 1))
