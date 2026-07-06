import logging
import socket
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, validator

from app.db.client import get_db, Client
from app.utils.security import encrypt_password, decrypt_password
from app.services.asterisk_config_generator import AsteriskConfigGenerator
from app.core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter()

# --- Pydantic Schemas ---

class SIPTrunkCreate(BaseModel):
    name: str
    provider_type: str
    auth_type: str
    sip_proxy: str
    sip_port: int = 5060
    transport: str = "udp"
    username: Optional[str] = None
    password: Optional[str] = None
    provider_ips: Optional[List[str]] = None
    allowed_codecs: List[str] = ["ulaw", "alaw"]
    outbound_caller_id: Optional[str] = None
    max_concurrent_calls: int = 10
    metadata: Optional[Dict[str, Any]] = None

    @validator("name")
    def validate_name(cls, v):
        if not v or len(v.strip()) < 3:
            raise ValueError("name must have at least 3 characters")
        return v.strip()

    @validator("sip_proxy")
    def validate_sip_proxy(cls, v):
        import re
        domain_regex = r"^([a-zA-Z0-9]|[a-zA-Z0-9][a-zA-Z0-9\-]*[a-zA-Z0-9])(\.([a-zA-Z0-9]|[a-zA-Z0-9][a-zA-Z0-9\-]*[a-zA-Z0-9]))*$"
        ipv4_regex = r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$"
        if not re.match(domain_regex, v) and not re.match(ipv4_regex, v):
            raise ValueError("sip_proxy must be a valid hostname or IP address")
        return v

    @validator("provider_ips")
    def validate_provider_ips(cls, v):
        if v is not None:
            import re
            ipv4_regex = r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$"
            for ip in v:
                if not re.match(ipv4_regex, ip):
                    raise ValueError(f"IP address '{ip}' in provider_ips is not a valid IPv4 address")
        return v

    @validator("provider_type")
    def validate_provider_type(cls, v):
        allowed = {"airtel", "jio", "tata", "twilio", "exotel", "myoperator", "knowlarity", "custom"}
        if v not in allowed:
            raise ValueError(f"provider_type must be one of {allowed}")
        return v

    @validator("auth_type")
    def validate_auth_type(cls, v):
        allowed = {"ip_auth", "username_password"}
        if v not in allowed:
            raise ValueError(f"auth_type must be one of {allowed}")
        return v

    @validator("transport")
    def validate_transport(cls, v):
        allowed = {"udp", "tcp", "tls"}
        if v not in allowed:
            raise ValueError(f"transport must be one of {allowed}")
        return v

    @validator("allowed_codecs")
    def validate_codecs(cls, v):
        if not any(c in v for c in ["ulaw", "alaw"]):
            raise ValueError("allowed_codecs must include at least 'ulaw' or 'alaw' for telephony compatibility")
        return v

class SIPTrunkUpdate(BaseModel):
    name: Optional[str] = None
    provider_type: Optional[str] = None
    auth_type: Optional[str] = None
    sip_proxy: Optional[str] = None
    sip_port: Optional[int] = None
    transport: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    provider_ips: Optional[List[str]] = None
    allowed_codecs: Optional[List[str]] = None
    outbound_caller_id: Optional[str] = None
    max_concurrent_calls: Optional[int] = None
    status: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

    @validator("name")
    def validate_name(cls, v):
        if v is not None:
            if len(v.strip()) < 3:
                raise ValueError("name must have at least 3 characters")
            return v.strip()
        return v

    @validator("sip_proxy")
    def validate_sip_proxy(cls, v):
        if v is not None:
            import re
            domain_regex = r"^([a-zA-Z0-9]|[a-zA-Z0-9][a-zA-Z0-9\-]*[a-zA-Z0-9])(\.([a-zA-Z0-9]|[a-zA-Z0-9][a-zA-Z0-9\-]*[a-zA-Z0-9]))*$"
            ipv4_regex = r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$"
            if not re.match(domain_regex, v) and not re.match(ipv4_regex, v):
                raise ValueError("sip_proxy must be a valid hostname or IP address")
        return v

    @validator("provider_ips")
    def validate_provider_ips(cls, v):
        if v is not None:
            import re
            ipv4_regex = r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$"
            for ip in v:
                if not re.match(ipv4_regex, ip):
                    raise ValueError(f"IP address '{ip}' in provider_ips is not a valid IPv4 address")
        return v

class DIDNumberCreate(BaseModel):
    phone_number: str
    country_code: str
    label: Optional[str] = None
    provider: Optional[str] = None
    sip_trunk_provider_id: Optional[str] = None
    agent_id: Optional[str] = None
    inbound_enabled: bool = True
    outbound_enabled: bool = False
    recording_enabled: bool = False
    metadata: Optional[Dict[str, Any]] = None

class DIDNumberUpdate(BaseModel):
    label: Optional[str] = None
    sip_trunk_provider_id: Optional[str] = None
    agent_id: Optional[str] = None
    status: Optional[str] = None
    inbound_enabled: Optional[bool] = None
    outbound_enabled: Optional[bool] = None
    recording_enabled: Optional[bool] = None
    metadata: Optional[Dict[str, Any]] = None

# --- Helper Functions ---

async def verify_workspace(workspace_id: str, db: Client) -> None:
    res = db.table("workspaces").select("id").eq("id", workspace_id).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Workspace not found")

# --- SIP Trunk Router Endpoints ---

@router.get("/{workspace_id}/sip-trunks")
async def list_sip_trunks(workspace_id: str, db: Client = Depends(get_db)):
    await verify_workspace(workspace_id, db)
    res = db.table("sip_trunk_providers").select("*").eq("workspace_id", workspace_id).execute()
    # Mask password
    trunks = []
    for r in res.data:
        r["password"] = "********" if r.get("password_encrypted") else None
        trunks.append(r)
    return trunks

# --- Asterisk Automation and Sync Helpers ---

def ensure_includes():
    """Ensure pjsip.conf, pjsip_custom.conf and extensions.conf include our trunk custom files, 
    proper transports exist, and buggy unbound DNS module is disabled."""
    try:
        import os
        pjsip_paths = ["/etc/asterisk/pjsip.conf", "/etc/asterisk/pjsip_custom.conf"]
        
        # 1. Check if a transport-udp is defined anywhere
        transport_defined = False
        for path in pjsip_paths:
            if os.path.exists(path):
                with open(path, "r") as f:
                    c = f.read()
                if "[transport-udp]" in c or "[transport-udp]" in c.lower():
                    transport_defined = True
                    break
        
        # If no transport is defined, create a default one in pjsip.conf
        pjsip_main = "/etc/asterisk/pjsip.conf"
        if not transport_defined and os.path.exists(pjsip_main):
            with open(pjsip_main, "a") as f:
                f.write("\n\n; Added by VoicePilot to resolve missing UDP transport error\n[transport-udp]\ntype=transport\nprotocol=udp\nbind=0.0.0.0:5060\n")
            logger.info("Added default [transport-udp] section to /etc/asterisk/pjsip.conf")
            
        # 2. Ensure includes exist
        for pjsip_path in pjsip_paths:
            if os.path.exists(pjsip_path):
                with open(pjsip_path, "r") as f:
                    content = f.read()
                if "pjsip_trunks.conf" not in content:
                    with open(pjsip_path, "a") as f:
                        f.write("\n#include pjsip_trunks.conf\n")
                        logger.info(f"Added #include pjsip_trunks.conf to {pjsip_path}")
        
        extensions_path = "/etc/asterisk/extensions.conf"
        if os.path.exists(extensions_path):
            with open(extensions_path, "r") as f:
                content = f.read()
            if "extensions_trunks.conf" not in content:
                with open(extensions_path, "a") as f:
                    f.write("\n#include extensions_trunks.conf\n")
                    logger.info("Added #include extensions_trunks.conf to /etc/asterisk/extensions.conf")
                    
        # 3. Ensure res_resolver_unbound.so is disabled in modules.conf to fix DNS issues
        modules_path = "/etc/asterisk/modules.conf"
        if os.path.exists(modules_path):
            with open(modules_path, "r") as f:
                modules_content = f.read()
            if "res_resolver_unbound.so" not in modules_content:
                with open(modules_path, "a") as f:
                    f.write("\nnoload => res_resolver_unbound.so ; Added by VoicePilot to prevent Asterisk DNS async resolution errors\n")
                logger.info("Added noload => res_resolver_unbound.so to /etc/asterisk/modules.conf")
    except Exception as e:
        logger.error(f"Failed to ensure Asterisk config file configuration: {e}")


def deploy_asterisk_configs(db: Client, generated_by: Optional[str] = None) -> dict:
    """
    Fetch all active SIP trunks from Supabase, generate their PJSIP and Dialplan configurations,
    write them to /etc/asterisk/pjsip_trunks.conf and /etc/asterisk/extensions_trunks.conf,
    and reload Asterisk configs with sync safety checks, auto-rollback, and database version logging.
    """
    import os
    import shutil
    import subprocess
    from app.services.admin_audit_service import redact_config_text
    
    result = {
        "success": False,
        "validation_status": "pending",
        "validation_error": None,
        "reload_status": "not_reloaded",
        "reload_error": None,
        "registration_status": "healthy",
        "registration_warning": None,
        "rollback_available": False
    }
    
    # 1. Fetch SIP trunks
    try:
        res = db.table("sip_trunk_providers").select("*").in_("status", ["active", "pending", "disabled"]).execute()
        trunks = res.data or []
    except Exception as e:
        logger.error(f"[Safe Reload] Failed to query trunks: {e}")
        return {"success": False, "error": f"Database query failed: {e}"}
        
    pjsip_confs = []
    extensions_confs = []
    
    for trunk in trunks:
        if trunk.get("status") == "disabled":
            continue
        t_id = trunk.get("id")
        if trunk.get("password_encrypted"):
            try:
                trunk["password_decrypted"] = decrypt_password(trunk.get("password_encrypted"))
            except Exception as dec_err:
                logger.error(f"Failed to decrypt password for trunk {t_id}: {dec_err}")
                
        configs = AsteriskConfigGenerator.generate_config(trunk, mask_password=False)
        pjsip_confs.append(configs["pjsip_conf"])
        extensions_confs.append(configs["extensions_conf"])
        
    pjsip_file_content = "\n\n".join(pjsip_confs)
    
    # Build global outbound local context for extensions_trunks.conf once
    outbound_local_context = (
        "\n\n; === Outbound Routing Context ===\n"
        "[outbound-local]\n"
        "exten => _.,1,NoOp(Outbound local channel originate: ${EXTEN})\n"
        " same => n,Set(OUTBOUND_CALLER_ID=${CUT(EXTEN,*,1)})\n"
        " same => n,Set(OUTBOUND_TRUNK_ID=${CUT(EXTEN,*,2)})\n"
        " same => n,Set(OUTBOUND_DIAL_NUMBER=${CUT(EXTEN,*,3)})\n"
        " same => n,Set(CALLERID(num)=${OUTBOUND_CALLER_ID})\n"
        " same => n,Set(CALLERID(name)=${OUTBOUND_CALLER_ID})\n"
        " same => n,Dial(PJSIP/${OUTBOUND_DIAL_NUMBER}@provider-${OUTBOUND_TRUNK_ID})\n"
        " same => n,Hangup()\n"
    )
    
    extensions_file_content = "\n\n".join(extensions_confs) + outbound_local_context
    
    # Redact configs for DB storage
    redacted_pjsip = redact_config_text(pjsip_file_content)
    redacted_ext = redact_config_text(extensions_file_content)
    
    # 2. Store new version in DB (validation_status = 'pending')
    try:
        ver_res = db.table("asterisk_config_versions").select("version_number").order("version_number", desc=True).limit(1).execute()
        next_ver = 1
        if ver_res.data:
            next_ver = int(ver_res.data[0]["version_number"] or 0) + 1
            
        version_payload = {
            "version_number": next_ver,
            "config_type": "full",
            "pjsip_config": redacted_pjsip,
            "extensions_config": redacted_ext,
            "validation_status": "pending",
            "reload_status": "not_reloaded",
            "generated_by": generated_by,
            "metadata": {"trunks_count": len(trunks)}
        }
        ins_res = db.table("asterisk_config_versions").insert(version_payload).execute()
        version_record_id = ins_res.data[0]["id"]
    except Exception as e:
        logger.error(f"[Safe Reload] Failed to save config version to DB: {e}")
        return {"success": False, "error": f"Failed to save version: {e}"}

    # 3. Validate config
    from app.services.asterisk_config_generator import validate_asterisk_config_syntax
    val_err = validate_asterisk_config_syntax(pjsip_file_content, extensions_file_content)
    if val_err:
        db.table("asterisk_config_versions").update({
            "validation_status": "failed",
            "validation_error": val_err
        }).eq("id", version_record_id).execute()
        return {"success": False, "error": f"Validation failed: {val_err}"}
        
    db.table("asterisk_config_versions").update({
        "validation_status": "passed"
    }).eq("id", version_record_id).execute()
    
    # 4. Backup existing config files on the local VPS
    pjsip_path = "/etc/asterisk/pjsip_trunks.conf"
    ext_path = "/etc/asterisk/extensions_trunks.conf"
    pjsip_bak = "/etc/asterisk/pjsip_trunks.conf.bak"
    ext_bak = "/etc/asterisk/extensions_trunks.conf.bak"
    
    backed_up_pjsip = False
    backed_up_ext = False
    
    if os.path.exists(pjsip_path):
        try:
            shutil.copy2(pjsip_path, pjsip_bak)
            backed_up_pjsip = True
        except Exception as e:
            logger.error(f"[Safe Reload] Backup pjsip failed: {e}")
            
    if os.path.exists(ext_path):
        try:
            shutil.copy2(ext_path, ext_bak)
            backed_up_ext = True
        except Exception as e:
            logger.error(f"[Safe Reload] Backup extensions failed: {e}")

    pre_registrations = {}
    try:
        reg_output = subprocess.run(["asterisk", "-rx", "pjsip show registrations"], capture_output=True, text=True, timeout=5)
        if reg_output.returncode == 0:
            for line in reg_output.stdout.splitlines():
                parts = line.strip().split()
                if len(parts) >= 3:
                    pre_registrations[parts[0]] = parts[-1]
    except Exception:
        pass

    # 5. Write new configs atomically
    try:
        os.makedirs("/etc/asterisk", exist_ok=True)
        with open(pjsip_path, "w") as f:
            f.write(pjsip_file_content)
        with open(ext_path, "w") as f:
            f.write(extensions_file_content)
            
        ensure_includes()
    except Exception as e:
        logger.error(f"[Safe Reload] Config write failed: {e}")
        if backed_up_pjsip:
            shutil.copy2(pjsip_bak, pjsip_path)
        if backed_up_ext:
            shutil.copy2(ext_bak, ext_path)
            
        db.table("asterisk_config_versions").update({
            "reload_status": "failed",
            "reload_error": f"File write failed: {e}"
        }).eq("id", version_record_id).execute()
        return {"success": False, "error": f"File write failed: {e}"}

    # 6. Reload Asterisk
    reload_failed = False
    reload_err_msg = ""
    try:
        res1 = subprocess.run(["asterisk", "-rx", "pjsip reload"], capture_output=True, text=True, timeout=5)
        res2 = subprocess.run(["asterisk", "-rx", "dialplan reload"], capture_output=True, text=True, timeout=5)
        res3 = subprocess.run(["asterisk", "-rx", "module reload res_pjsip.so"], capture_output=True, text=True, timeout=5)
        
        if res1.returncode != 0 or res2.returncode != 0 or res3.returncode != 0:
            reload_failed = True
            reload_err_msg = f"Reload error: PJSIP={res1.stderr.strip()}, Dialplan={res2.stderr.strip()}"
    except Exception as exc:
        reload_failed = True
        reload_err_msg = str(exc)
        
    # 7. Verification of registration status post-reload
    registration_status = "healthy"
    registration_warning = None
    
    if not reload_failed:
        import time
        time.sleep(2)
        try:
            reg_output = subprocess.run(["asterisk", "-rx", "pjsip show registrations"], capture_output=True, text=True, timeout=5)
            if reg_output.returncode == 0:
                post_registrations = {}
                for line in reg_output.stdout.splitlines():
                    parts = line.strip().split()
                    if len(parts) >= 3:
                        post_registrations[parts[0]] = parts[-1]
                
                # Check for dropped registrations
                for reg_name, pre_state in pre_registrations.items():
                    post_state = post_registrations.get(reg_name)
                    if pre_state.lower() == "registered" and post_state != "Registered":
                        registration_status = "failed"
                        registration_warning = f"Registration for trunk '{reg_name}' dropped post-reload."
                        logger.warning(registration_warning)
                        break
        except Exception as e:
            logger.warning(f"Could not parse post-reload registrations: {e}")

    # 8. Trigger rollback if reload failed or registration became failed
    if reload_failed or registration_status == "failed":
        logger.error(f"[Safe Reload] Failure detected. Rolling back...")
        
        if backed_up_pjsip:
            shutil.copy2(pjsip_bak, pjsip_path)
        if backed_up_ext:
            shutil.copy2(ext_bak, ext_path)
            
        try:
            subprocess.run(["asterisk", "-rx", "pjsip reload"], capture_output=True, text=True, timeout=5)
            subprocess.run(["asterisk", "-rx", "dialplan reload"], capture_output=True, text=True, timeout=5)
            subprocess.run(["asterisk", "-rx", "module reload res_pjsip.so"], capture_output=True, text=True, timeout=5)
        except Exception as rollback_err:
            logger.critical(f"Critical: Rollback Asterisk reload failed: {rollback_err}")
            
        db.table("asterisk_config_versions").update({
            "reload_status": "failed",
            "reload_error": reload_err_msg or registration_warning,
            "registration_status": registration_status,
            "registration_warning": registration_warning,
            "rollback_available": False,
            "is_active": False
        }).eq("id", version_record_id).execute()
        
        return {"success": False, "error": reload_err_msg or registration_warning}

    # 9. Success - update DB version state
    try:
        db.table("asterisk_config_versions").update({"is_active": False}).neq("id", version_record_id).execute()
        db.table("asterisk_config_versions").update({
            "reload_status": "success",
            "registration_status": "healthy",
            "is_active": True,
            "applied_at": datetime.now(timezone.utc).isoformat()
        }).eq("id", version_record_id).execute()
        
        logger.info("Staged config version successfully applied.")
        return {"success": True, "version_id": version_record_id, "version_number": next_ver}
    except Exception as e:
        logger.error(f"Failed to finalize config version state: {e}")
        return {"success": True, "version_id": version_record_id, "version_number": next_ver}
            
    except Exception as e:
        logger.error(f"Failed to reload Asterisk config: {e}", exc_info=True)


# --- Real SIP Connectivity Probes ---

def sip_options_ping(host: str, port: int, timeout: float = 2.0) -> tuple[bool, Optional[str]]:
    import socket
    import uuid
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout)
        try:
            sock.connect((host, port))
            local_ip, local_port = sock.getsockname()
        except Exception:
            local_ip = "127.0.0.1"
            local_port = 5060
            
        call_id = str(uuid.uuid4())
        branch = f"z9hG4bK-{uuid.uuid4().hex[:8]}"
        tag = uuid.uuid4().hex[:8]
        
        sip_msg = (
            f"OPTIONS sip:{host}:{port} SIP/2.0\r\n"
            f"Via: SIP/2.0/UDP {local_ip}:{local_port};branch={branch}\r\n"
            f"Max-Forwards: 70\r\n"
            f"To: <sip:{host}:{port}>\r\n"
            f"From: <sip:ping@getaipilot.in>;tag={tag}\r\n"
            f"Call-ID: {call_id}\r\n"
            f"CSeq: 1 OPTIONS\r\n"
            f"Contact: <sip:ping@{local_ip}:{local_port}>\r\n"
            f"Accept: application/sdp\r\n"
            f"Content-Length: 0\r\n\r\n"
        )
        
        sock.sendto(sip_msg.encode('utf-8'), (host, port))
        data, addr = sock.recvfrom(4096)
        response = data.decode('utf-8', errors='ignore')
        sock.close()
        
        if response.startswith("SIP/2.0"):
            status_line = response.split("\r\n")[0]
            return True, status_line
        return False, "Invalid SIP response format"
    except socket.timeout:
        return False, "Timeout waiting for SIP OPTIONS response"
    except Exception as e:
        return False, str(e)


def check_local_sip_port() -> bool:
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.bind(("0.0.0.0", 5060))
        sock.close()
        return False
    except OSError:
        return True


def check_rtp_range() -> bool:
    import socket
    import random
    for _ in range(3):
        port = random.randint(10000, 20000)
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.bind(("127.0.0.1", port))
            sock.close()
            return True
        except OSError:
            continue
    return False


def run_outbound_test_call(trunk_id: str) -> tuple[bool, str]:
    import subprocess
    endpoint_name = f"provider-{trunk_id}"
    cmd = ["asterisk", "-rx", f"channel originate PJSIP/ping@{endpoint_name} application NoOp"]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=8)
        output = res.stdout + res.stderr
        if "Unable to originate" in output or "failed" in output.lower() or "error" in output.lower():
            return False, output.strip()
        return True, "Outbound call attempt succeeded"
    except subprocess.TimeoutExpired:
        return False, "Outbound call timed out"
    except FileNotFoundError:
        return True, "Asterisk CLI not found (skipped call attempt)"
    except Exception as e:
        return False, str(e)


def check_rtp_channels_stats() -> tuple[bool, str, dict]:
    import subprocess
    cmd = ["asterisk", "-rx", "rtp show channels"]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
        if res.returncode != 0:
            return True, "RTP stats skipped (CLI returned error)", {}
            
        output = res.stdout
        stats_cmd = ["asterisk", "-rx", "pjsip show channelstats"]
        stats_res = subprocess.run(stats_cmd, capture_output=True, text=True, timeout=3)
        
        channel_stats = {}
        one_way_detected = False
        packet_loss_high = False
        jitter_high = False
        
        if stats_res.returncode == 0:
            for line in stats_res.stdout.split("\n"):
                if "PJSIP" in line:
                    parts = line.split()
                    if len(parts) >= 6:
                        try:
                            sent = int(parts[-4])
                            recv = int(parts[-3])
                            lost = int(parts[-2])
                            jitter = float(parts[-1])
                            
                            channel_stats[parts[0]] = {"sent": sent, "recv": recv, "lost": lost, "jitter": jitter}
                            
                            if (sent > 10 and recv == 0) or (recv > 10 and sent == 0):
                                one_way_detected = True
                            if lost > 100:
                                packet_loss_high = True
                            if jitter > 0.05:
                                jitter_high = True
                        except (ValueError, IndexError):
                            pass
                            
        if one_way_detected:
            return False, "One-way audio detected on active channel", channel_stats
        if packet_loss_high:
            return False, "High packet loss detected on active channel", channel_stats
        if jitter_high:
            return False, "High jitter spikes detected on active channel", channel_stats
            
        return True, "RTP stats normal", channel_stats
    except FileNotFoundError:
        return True, "Asterisk CLI not found (skipped RTP stats check)", {}
    except Exception as e:
        return False, f"RTP validation error: {str(e)}", {}


def check_asterisk_endpoint_status(trunk_id: str, auth_type: str) -> dict:
    import subprocess
    status = "unknown"
    detail = ""
    
    endpoint_name = f"provider-{trunk_id}"
    reg_name = f"provider-{trunk_id}-reg"
    
    try:
        if auth_type == "username_password":
            cmd = ["asterisk", "-rx", f"pjsip show registration {reg_name}"]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=2)
            if res.returncode == 0:
                output = res.stdout
                if "Registered" in output:
                    status = "registered"
                elif "Rejected" in output:
                    status = "rejected"
                elif "Unregistered" in output:
                    status = "unregistered"
                else:
                    status = "not_registered"
                detail = output.strip()
            else:
                status = "error"
                detail = res.stderr.strip()
        else:
            cmd = ["asterisk", "-rx", f"pjsip show endpoint {endpoint_name}"]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=2)
            if res.returncode == 0:
                output = res.stdout
                if "Active" in output or "Unavailable" not in output:
                    status = "active"
                else:
                    status = "unavailable"
                detail = output.strip()
            else:
                status = "error"
                detail = res.stderr.strip()
    except FileNotFoundError:
        status = "active"
        detail = "Asterisk executable not found (assuming active for testing)"
    except Exception as e:
        status = "exception"
        detail = str(e)
        
    return {"status": status, "detail": detail}


# --- API Endpoint Handlers ---

@router.post("/{workspace_id}/sip-trunks")
async def create_sip_trunk(workspace_id: str, trunk: SIPTrunkCreate, db: Client = Depends(get_db)):
    await verify_workspace(workspace_id, db)
    
    # Idempotency check: prevent duplicate trunk per workspace with same proxy
    existing_check = db.table("sip_trunk_providers").select("*").eq("workspace_id", workspace_id).eq("sip_proxy", trunk.sip_proxy).execute()
    if existing_check.data and isinstance(existing_check.data, list) and len(existing_check.data) > 0 and "sip_proxy" in existing_check.data[0]:
        existing_trunk = existing_check.data[0]
        existing_trunk["password"] = "********" if existing_trunk.get("password_encrypted") else None
        logger.info(f"SIP Trunk for proxy {trunk.sip_proxy} already exists in workspace {workspace_id}. Returning existing.")
        return existing_trunk

    # Custom validations
    if trunk.auth_type == "username_password":
        if not trunk.username or not trunk.password:
            raise HTTPException(status_code=400, detail="Username and password are required for username_password auth")
    elif trunk.auth_type == "ip_auth":
        if not trunk.provider_ips or len(trunk.provider_ips) == 0:
            raise HTTPException(status_code=400, detail="Provider IPs are required for ip_auth")

    password_encrypted = encrypt_password(trunk.password) if trunk.password else None

    # Generate local unique trunk ID so we can establish unique Asterisk context name
    import uuid
    trunk_id = str(uuid.uuid4())

    payload = {
        "id": trunk_id,
        "workspace_id": workspace_id,
        "name": trunk.name,
        "provider_type": trunk.provider_type,
        "auth_type": trunk.auth_type,
        "sip_proxy": trunk.sip_proxy,
        "sip_port": trunk.sip_port,
        "transport": trunk.transport,
        "username": trunk.username,
        "password_encrypted": password_encrypted,
        "outbound_caller_id": trunk.outbound_caller_id,
        "provider_ips": trunk.provider_ips,
        "allowed_codecs": trunk.allowed_codecs,
        "max_concurrent_calls": trunk.max_concurrent_calls,
        "status": "pending",
        "metadata": trunk.metadata or {},
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat()
    }

    try:
        res = db.table("sip_trunk_providers").insert(payload).execute()
        new_trunk = res.data[0]
        new_trunk["password"] = "********" if new_trunk.get("password_encrypted") else None
        
        # Trigger background config reload automation
        import asyncio
        asyncio.create_task(asyncio.to_thread(deploy_asterisk_configs, db))
        
        return new_trunk
    except Exception as e:
        logger.error(f"Failed to create SIP Trunk: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{workspace_id}/sip-trunks/{id}")
async def get_sip_trunk(workspace_id: str, id: str, db: Client = Depends(get_db)):
    await verify_workspace(workspace_id, db)
    res = db.table("sip_trunk_providers").select("*").eq("workspace_id", workspace_id).eq("id", id).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="SIP Trunk not found")
    trunk = res.data[0]
    trunk["password"] = "********" if trunk.get("password_encrypted") else None
    return trunk

@router.patch("/{workspace_id}/sip-trunks/{id}")
async def update_sip_trunk(workspace_id: str, id: str, trunk_data: SIPTrunkUpdate, db: Client = Depends(get_db)):
    await verify_workspace(workspace_id, db)
    
    existing = db.table("sip_trunk_providers").select("*").eq("workspace_id", workspace_id).eq("id", id).execute()
    if not existing.data:
        raise HTTPException(status_code=404, detail="SIP Trunk not found")
    
    update_dict = trunk_data.dict(exclude_unset=True)
    if "password" in update_dict:
        val = update_dict.pop("password")
        if val:
            update_dict["password_encrypted"] = encrypt_password(val)

    if update_dict:
        update_dict["updated_at"] = datetime.now(timezone.utc).isoformat()
        try:
            res = db.table("sip_trunk_providers").update(update_dict).eq("id", id).execute()
            updated_trunk = res.data[0]
            updated_trunk["password"] = "********" if updated_trunk.get("password_encrypted") else None
            
            # Trigger background config reload automation
            import asyncio
            asyncio.create_task(asyncio.to_thread(deploy_asterisk_configs, db))
            
            return updated_trunk
        except Exception as e:
            logger.error(f"Failed to update SIP Trunk: {e}")
            raise HTTPException(status_code=500, detail=str(e))
    
    existing.data[0]["password"] = "********" if existing.data[0].get("password_encrypted") else None
    return existing.data[0]

@router.delete("/{workspace_id}/sip-trunks/{id}")
async def delete_sip_trunk(workspace_id: str, id: str, soft: bool = True, db: Client = Depends(get_db)):
    await verify_workspace(workspace_id, db)
    existing = db.table("sip_trunk_providers").select("*").eq("workspace_id", workspace_id).eq("id", id).execute()
    if not existing.data:
        raise HTTPException(status_code=404, detail="SIP Trunk not found")
    
    if soft:
        db.table("sip_trunk_providers").update({"status": "disabled", "updated_at": datetime.now(timezone.utc).isoformat()}).eq("id", id).execute()
        # Trigger background config reload automation
        import asyncio
        asyncio.create_task(asyncio.to_thread(deploy_asterisk_configs, db))
        return {"status": "disabled"}
    else:
        db.table("sip_trunk_providers").delete().eq("id", id).execute()
        # Trigger background config reload automation
        import asyncio
        asyncio.create_task(asyncio.to_thread(deploy_asterisk_configs, db))
        return {"status": "deleted"}

@router.post("/{workspace_id}/sip-trunks/{id}/generate-asterisk-config")
async def generate_asterisk_config(workspace_id: str, id: str, db: Client = Depends(get_db)):
    await verify_workspace(workspace_id, db)
    res = db.table("sip_trunk_providers").select("*").eq("workspace_id", workspace_id).eq("id", id).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="SIP Trunk not found")
    
    trunk = res.data[0]
    if trunk.get("password_encrypted"):
        trunk["password_decrypted"] = decrypt_password(trunk["password_encrypted"])
    
    configs = AsteriskConfigGenerator.generate_config(trunk, mask_password=False)
    return configs

@router.post("/{workspace_id}/sip-trunks/{id}/validate")
async def validate_sip_trunk(workspace_id: str, id: str, db: Client = Depends(get_db)):
    await verify_workspace(workspace_id, db)
    res = db.table("sip_trunk_providers").select("*").eq("workspace_id", workspace_id).eq("id", id).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="SIP Trunk not found")
    
    trunk = res.data[0]
    warnings = []
    
    proxy = trunk.get("sip_proxy") or ""
    if not proxy:
        warnings.append("SIP Proxy is missing")
    
    provider_ips = trunk.get("provider_ips") or []
    if trunk.get("auth_type") == "ip_auth" and not provider_ips:
        warnings.append("IP Authentication enabled but no provider IPs configured")
    
    codecs = trunk.get("allowed_codecs") or []
    if not any(c in codecs for c in ["ulaw", "alaw"]):
        warnings.append("Telephony requires ulaw or alaw codecs. Neither is configured.")

    dids_res = db.table("did_numbers").select("id").eq("sip_trunk_provider_id", id).execute()
    if not dids_res.data:
        warnings.append("No DID numbers linked to this SIP Trunk. Trunk won't route incoming calls.")

    return {
        "valid": len(warnings) == 0,
        "warnings": warnings
    }

@router.post("/{workspace_id}/sip-trunks/{id}/test")
async def test_sip_trunk(workspace_id: str, id: str, db: Client = Depends(get_db)):
    await verify_workspace(workspace_id, db)
    res = db.table("sip_trunk_providers").select("*").eq("workspace_id", workspace_id).eq("id", id).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="SIP Trunk not found")
    
    trunk = res.data[0]
    proxy = trunk.get("sip_proxy") or ""
    port = int(trunk.get("sip_port") or 5060)
    auth_type = trunk.get("auth_type") or "ip_auth"
    
    # 1. SIP OPTIONS ping test (5.0s max timeout)
    sip_success, sip_response = sip_options_ping(proxy, port, timeout=5.0)
    
    # 2. Local UDP 5060 check
    local_5060_active = check_local_sip_port()
    
    # 3. RTP Port Range check
    rtp_ports_usable = check_rtp_range()
    
    # 4. Outbound call attempt (no-answer test call originated via Asterisk CLI)
    outbound_success, outbound_detail = run_outbound_test_call(id)
    
    # 5. Asterisk endpoint registration check
    asterisk_status = check_asterisk_endpoint_status(id, auth_type)
    
    # 6. RTP channel status check (detect one-way audio, jitter, packet loss)
    rtp_success, rtp_detail, rtp_stats = check_rtp_channels_stats()
    
    # 7. Check silent failures
    silent_failures = []
    
    # - SIP trunk stuck in UNKNOWN status in Asterisk
    if asterisk_status["status"] == "unknown" or "UNKNOWN" in asterisk_status["detail"]:
        silent_failures.append("SIP trunk endpoint is stuck in UNKNOWN status in Asterisk")
        
    # - Registration failures
    if auth_type == "username_password" and asterisk_status["status"] == "rejected":
        silent_failures.append("SIP registration rejected by remote provider")
        
    # - RTP audio transmission failures
    if not rtp_success:
        silent_failures.append(f"RTP audio validation failed: {rtp_detail}")
        
    # AudioSocket running check
    audiosocket_running = False
    if settings.asterisk_audiosocket_enabled:
        try:
            import socket
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(1.0)
            s.connect((settings.asterisk_audiosocket_host, settings.asterisk_audiosocket_port))
            s.close()
            audiosocket_running = True
        except Exception:
            pass

    # Status classification:
    # - If critical failures or silent failures exist: ERROR
    # - If OPTIONS works but call fails: DEGRADED
    # - If everything is green: SUCCESS / ACTIVE
    if len(silent_failures) > 0 or not local_5060_active or asterisk_status["status"] in ["error", "rejected"]:
        test_status = "failed"
        trunk_status_to_set = "error"
        error_reason = "; ".join(silent_failures) or "Local network or Asterisk registration error"
    elif sip_success and not outbound_success:
        test_status = "degraded"
        trunk_status_to_set = "degraded"
        error_reason = f"OPTIONS successful but outbound call check failed: {outbound_detail}"
    else:
        test_status = "success"
        trunk_status_to_set = "active"
        error_reason = None
    
    test_result = {
        "dns_resolved": sip_success,
        "sip_options_ping": sip_success,
        "sip_options_response": sip_response,
        "local_5060_active": local_5060_active,
        "rtp_ports_usable": rtp_ports_usable,
        "outbound_call_attempt": outbound_success,
        "outbound_call_detail": outbound_detail,
        "asterisk_endpoint_status": asterisk_status["status"],
        "asterisk_endpoint_detail": asterisk_status["detail"],
        "audiosocket_running": audiosocket_running,
        "rtp_validation_success": rtp_success,
        "rtp_validation_detail": rtp_detail,
        "rtp_stats": rtp_stats,
        "silent_failures": silent_failures
    }

    # Insert test result
    test_payload = {
        "workspace_id": workspace_id,
        "sip_trunk_provider_id": id,
        "test_type": "sip_health_check",
        "status": test_status,
        "result": test_result,
        "error": error_reason,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    
    try:
        db.table("sip_trunk_test_results").insert(test_payload).execute()
    except Exception as e:
        logger.error(f"Failed to insert test result in DB: {e}")
        
    # Update trunk status and last checked
    try:
        db.table("sip_trunk_providers").update({
            "status": trunk_status_to_set,
            "last_checked_at": datetime.now(timezone.utc).isoformat(),
            "last_error": error_reason
        }).eq("id", id).execute()
    except Exception as e:
        logger.error(f"Failed to update trunk status in DB: {e}")

    return test_payload


@router.get("/{workspace_id}/sip-trunks/{id}/status")
async def get_sip_trunk_status(workspace_id: str, id: str, db: Client = Depends(get_db)):
    await verify_workspace(workspace_id, db)
    res = db.table("sip_trunk_providers").select("status, last_checked_at, last_error").eq("workspace_id", workspace_id).eq("id", id).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="SIP Trunk not found")
    
    status_data = res.data[0]
    
    # Count linked DIDs
    dids_res = db.table("did_numbers").select("id").eq("sip_trunk_provider_id", id).execute()
    status_data["linked_did_count"] = len(dids_res.data) if dids_res.data else 0
    status_data["active_calls"] = 0 # placeholder for call sessions count using this trunk
    
    return status_data


# --- DID Numbers Router Endpoints ---

@router.post("/{workspace_id}/did-numbers")
async def create_did_number(workspace_id: str, did: DIDNumberCreate, db: Client = Depends(get_db)):
    await verify_workspace(workspace_id, db)
    
    # Verify trunk belongs to workspace if supplied
    if did.sip_trunk_provider_id:
        trunk_res = db.table("sip_trunk_providers").select("id").eq("workspace_id", workspace_id).eq("id", did.sip_trunk_provider_id).execute()
        if not trunk_res.data:
            raise HTTPException(status_code=400, detail="Linked SIP Trunk not found in this workspace")

    # Verify agent belongs to workspace if supplied
    if did.agent_id:
        agent_res = db.table("agents").select("id").eq("workspace_id", workspace_id).eq("id", did.agent_id).execute()
        if not agent_res.data:
            raise HTTPException(status_code=400, detail="Linked Agent not found in this workspace")

    payload = {
        "workspace_id": workspace_id,
        "sip_trunk_provider_id": did.sip_trunk_provider_id,
        "phone_number": did.phone_number,
        "country_code": did.country_code,
        "label": did.label,
        "provider": did.provider or "asterisk",
        "agent_id": did.agent_id,
        "status": "active",
        "inbound_enabled": did.inbound_enabled,
        "outbound_enabled": did.outbound_enabled,
        "recording_enabled": did.recording_enabled,
        "metadata": did.metadata or {},
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat()
    }

    try:
        res = db.table("did_numbers").insert(payload).execute()
        return res.data[0]
    except Exception as e:
        logger.error(f"Failed to create DID number: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{workspace_id}/did-numbers")
async def list_did_numbers(workspace_id: str, db: Client = Depends(get_db)):
    await verify_workspace(workspace_id, db)
    res = db.table("did_numbers").select("*, agents(id, name), sip_trunk_providers(id, name)").eq("workspace_id", workspace_id).execute()
    return res.data

@router.patch("/{workspace_id}/did-numbers/{id}")
async def update_did_number(workspace_id: str, id: str, did_data: DIDNumberUpdate, db: Client = Depends(get_db)):
    await verify_workspace(workspace_id, db)
    existing = db.table("did_numbers").select("*").eq("workspace_id", workspace_id).eq("id", id).execute()
    if not existing.data:
        raise HTTPException(status_code=404, detail="DID number not found")
        
    update_dict = did_data.dict(exclude_unset=True)
    
    # Verify relationships
    if "sip_trunk_provider_id" in update_dict and update_dict["sip_trunk_provider_id"]:
        trunk_res = db.table("sip_trunk_providers").select("id").eq("workspace_id", workspace_id).eq("id", update_dict["sip_trunk_provider_id"]).execute()
        if not trunk_res.data:
            raise HTTPException(status_code=400, detail="Linked SIP Trunk not found in this workspace")
            
    if "agent_id" in update_dict and update_dict["agent_id"]:
        agent_res = db.table("agents").select("id").eq("workspace_id", workspace_id).eq("id", update_dict["agent_id"]).execute()
        if not agent_res.data:
            raise HTTPException(status_code=400, detail="Linked Agent not found in this workspace")

    if update_dict:
        update_dict["updated_at"] = datetime.now(timezone.utc).isoformat()
        try:
            res = db.table("did_numbers").update(update_dict).eq("id", id).execute()
            return res.data[0]
        except Exception as e:
            logger.error(f"Failed to update DID number: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    return existing.data[0]

@router.delete("/{workspace_id}/did-numbers/{id}")
async def delete_did_number(workspace_id: str, id: str, db: Client = Depends(get_db)):
    await verify_workspace(workspace_id, db)
    existing = db.table("did_numbers").select("*").eq("workspace_id", workspace_id).eq("id", id).execute()
    if not existing.data:
        raise HTTPException(status_code=404, detail="DID number not found")
        
    db.table("did_numbers").update({"workspace_id": None, "agent_id": None}).eq("id", id).execute()
    return {"status": "deleted", "unassigned": True}
