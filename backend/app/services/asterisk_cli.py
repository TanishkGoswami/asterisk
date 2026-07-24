import os
import platform
import shutil
import subprocess
import shlex
import logging
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

def execute_asterisk_cli_cmd(asterisk_cmd: str, timeout: float = 30.0) -> Dict[str, Any]:
    """
    Executes an Asterisk CLI command either locally, via WSL, or via SSH.
    """
    from app.core.config import settings

    use_ssh = settings.use_ssh_for_asterisk
    
    if use_ssh:
        ssh_host = settings.asterisk_ssh_host
        ssh_user = settings.asterisk_ssh_user
        ssh_key = settings.asterisk_ssh_key_path or ""
        
        # Build SSH command
        cmd_list = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5"]
        if ssh_key:
            cmd_list += ["-i", ssh_key]
        cmd_list += [
            f"{ssh_user}@{ssh_host}",
            f"asterisk -rx {shlex.quote(asterisk_cmd)}"
        ]
        method = "ssh"
    else:
        # Detect execution mode: auto | local | wsl
        mode = os.getenv("ASTERISK_EXECUTION_MODE", "auto").lower()
        asterisk_bin = os.getenv("ASTERISK_BINARY", "asterisk")
        distro = os.getenv("ASTERISK_WSL_DISTRO", "")

        system = platform.system()
        
        # Auto-detection
        if mode == "auto":
            # If running on Windows, control Asterisk inside WSL
            if system == "Windows":
                mode = "wsl"
            else:
                mode = "local"

        if mode == "wsl":
            wsl_bin = shutil.which("wsl.exe") or shutil.which("wsl")
            if not wsl_bin:
                wsl_bin = "wsl.exe"
            
            cmd_list = [wsl_bin]
            if distro:
                cmd_list += ["-d", distro]
            cmd_list += ["-u", "root", asterisk_bin, "-rx", asterisk_cmd]
            method = "wsl"
        else:
            cmd_list = [asterisk_bin, "-rx", asterisk_cmd]
            method = "local"

    logger.info(f"[Asterisk CLI] Executing command via {method}: {shlex.join(cmd_list)}")
    try:
        res = subprocess.run(cmd_list, capture_output=True, text=True, timeout=timeout)
        logger.info(f"[Asterisk CLI] Result - Code: {res.returncode}")
        stdout_val = res.stdout or ""
        stderr_val = res.stderr or ""
        
        if res.returncode != 0:
            logger.warning(f"[Asterisk CLI] Command failed with exit code {res.returncode}. Stderr: {stderr_val.strip()}")
            
        return {
            "returncode": res.returncode,
            "stdout": stdout_val,
            "stderr": stderr_val,
            "full_cmd": shlex.join(cmd_list),
            "execution_method": method
        }
    except FileNotFoundError as e:
        err_msg = f"Executable not found during execution of Asterisk CLI: {e}"
        logger.error(f"[Asterisk CLI] {err_msg}")
        return {
            "returncode": -1,
            "stdout": "",
            "stderr": err_msg,
            "full_cmd": shlex.join(cmd_list),
            "execution_method": method
        }
    except subprocess.TimeoutExpired as e:
        err_msg = f"Command timed out after {timeout} seconds: {e}"
        logger.error(f"[Asterisk CLI] {err_msg}")
        return {
            "returncode": -2,
            "stdout": "",
            "stderr": err_msg,
            "full_cmd": shlex.join(cmd_list),
            "execution_method": method
        }
    except Exception as e:
        err_msg = f"Execution failed due to unexpected error: {e}"
        logger.error(f"[Asterisk CLI] {err_msg}", exc_info=True)
        return {
            "returncode": -3,
            "stdout": "",
            "stderr": err_msg,
            "full_cmd": shlex.join(cmd_list),
            "execution_method": method
        }

def verify_endpoint_status(endpoint_name: str) -> Dict[str, Any]:
    """
    Verifies the status of a PJSIP endpoint in Asterisk.
    Returns a dict with keys:
    - 'status': 'valid' | 'missing' | 'unavailable' | 'cli_error'
    - 'message': user-facing descriptive message
    - 'details': internal debugging details (command run, code, stdout, stderr, etc.)
    """
    res = execute_asterisk_cli_cmd(f"pjsip show endpoint {endpoint_name}")
    ret_code = res.get("returncode", -1)
    stdout_val = res.get("stdout", "")
    stderr_val = res.get("stderr", "")
    full_cmd = res.get("full_cmd", "")
    method = res.get("execution_method", "")
    
    details = {
        "command": full_cmd,
        "method": method,
        "returncode": ret_code,
        "stdout_summary": stdout_val.strip()[:200],
        "stderr": stderr_val.strip()
    }
    
    if ret_code in (-1, -2, -3):
        return {
            "status": "cli_error",
            "message": f"Could not execute Asterisk command. Internal details: {stderr_val.strip()}",
            "details": details
        }
        
    if "unable to connect" in stdout_val.lower() or "unable to connect" in stderr_val.lower():
        return {
            "status": "unavailable",
            "message": "Asterisk service is not running or the current user lacks permissions to access Asterisk control socket (/var/run/asterisk/asterisk.ctl).",
            "details": details
        }
        
    if "unable to find" in stdout_val.lower() or "not found" in stdout_val.lower() or "unable to find" in stderr_val.lower() or "not found" in stderr_val.lower():
        return {
            "status": "missing",
            "message": f"SIP Trunk Endpoint '{endpoint_name}' does not exist in Asterisk. Please check your PJSIP configuration.",
            "details": details
        }
        
    if ret_code != 0:
        return {
            "status": "cli_error",
            "message": f"Asterisk CLI command returned non-zero code {ret_code}. Stderr: {stderr_val.strip()}",
            "details": details
        }
        
    return {
        "status": "valid",
        "message": f"SIP Trunk Endpoint '{endpoint_name}' is valid.",
        "details": details
    }
