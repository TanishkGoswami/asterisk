import logging
import re
from typing import Dict, Any, Optional
from fastapi import Request
from app.db.client import Client

logger = logging.getLogger(__name__)

# Sensitive key terms that should be masked/redacted
SECRET_KEYS = {
    "password", "secret", "auth_pass", "token", "api_key", "key", "jwt",
    "ami_password", "webhook_secret", "password_encrypted", "auth_token",
    "credential", "credentials", "raw_password", "sip_password", "api_secret"
}

def mask_secret(value: str) -> str:
    """Mask a secret string leaving first 3 and last 4 characters visible if long enough."""
    if not value:
        return ""
    val_str = str(value)
    if len(val_str) <= 8:
        return "********"
    return f"{val_str[:3]}********{val_str[-4:]}"

def sanitize_admin_payload(payload: Any) -> Any:
    """Recursively traverses a dictionary or list, masking values of sensitive keys."""
    if isinstance(payload, dict):
        sanitized = {}
        for k, v in payload.items():
            k_lower = k.lower()
            if any(term in k_lower for term in SECRET_KEYS):
                if v is not None:
                    sanitized[k] = mask_secret(str(v))
                else:
                    sanitized[k] = None
            else:
                sanitized[k] = sanitize_admin_payload(v)
        return sanitized
    elif isinstance(payload, list):
        return [sanitize_admin_payload(item) for item in payload]
    return payload

def redact_config_text(config_text: str) -> str:
    """Redacts passwords and secrets from configuration file text formats (ini/config blocks)."""
    if not config_text:
        return ""
    
    lines = config_text.splitlines()
    redacted_lines = []
    
    # Pattern to match config/ini entries like: password = some_value or secret=some_value
    # Group 1: Key, Group 2: Assignment, Group 3: Value
    pattern = re.compile(r"^(\s*[\w\-\.]+)\s*(=|:)\s*(.*)$")
    
    for line in lines:
        match = pattern.match(line)
        if match:
            key, assign, val = match.groups()
            key_lower = key.lower()
            if any(term in key_lower for term in SECRET_KEYS):
                masked_val = mask_secret(val.strip())
                redacted_lines.append(f"{key} {assign} {masked_val}")
            else:
                redacted_lines.append(line)
        else:
            redacted_lines.append(line)
            
    return "\n".join(redacted_lines)

async def log_admin_action(
    db: Client,
    admin_user_id: Optional[str],
    action: str,
    target_type: Optional[str] = None,
    target_id: Optional[str] = None,
    old_value: Optional[Any] = None,
    new_value: Optional[Any] = None,
    metadata: Optional[dict] = None,
    request: Optional[Request] = None
) -> None:
    """Logs administrative action to database, ensuring all payloads are sanitized of sensitive keys."""
    try:
        ip_address = None
        user_agent = None
        if request:
            ip_address = request.client.host if request.client else None
            user_agent = request.headers.get("user-agent")

        sanitized_old = sanitize_admin_payload(old_value) if old_value else {}
        sanitized_new = sanitize_admin_payload(new_value) if new_value else {}

        db.table("admin_audit_logs").insert({
            "admin_user_id": admin_user_id,
            "action": action,
            "target_type": target_type,
            "target_id": target_id,
            "old_value": sanitized_old,
            "new_value": sanitized_new,
            "metadata": metadata or {},
            "ip_address": ip_address,
            "user_agent": user_agent
        }).execute()
        logger.info(f"[Audit Log] admin_user_id={admin_user_id} executed action={action} on target={target_type}:{target_id}")
    except Exception as e:
        logger.error(f"[Audit Log Error] Failed to log admin action: {e}", exc_info=True)
