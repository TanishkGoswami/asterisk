import logging
from typing import Dict, Any, List, Optional
from app.core.config import settings

logger = logging.getLogger(__name__)

class AsteriskConfigGenerator:
    @staticmethod
    def generate_config(trunk: Dict[str, Any], mask_password: bool = True) -> Dict[str, str]:
        """
        Generate pjsip.conf, extensions.conf, firewall commands, and reload commands for a SIP Trunk.
        """
        trunk_id = trunk.get("id", "template-id")
        name = trunk.get("name", "SIP-Trunk")
        auth_type = trunk.get("auth_type", "ip_auth")
        sip_proxy = trunk.get("sip_proxy", "127.0.0.1")
        sip_port = trunk.get("sip_port", 5060)
        transport = trunk.get("transport", "udp")
        username = trunk.get("username", "")
        
        try:
            port_val = int(sip_port) if sip_port else 5060
        except ValueError:
            port_val = 5060
        port_suffix = f":{sip_port}" if port_val != 5060 else ""
        
        # Get password, check if it's already decrypted/plain-text
        password = trunk.get("password", "") or trunk.get("password_decrypted", "")
        if mask_password and password:
            password = "********"

        provider_ips = trunk.get("provider_ips") or []
        if isinstance(provider_ips, str):
            import json
            try:
                provider_ips = json.loads(provider_ips)
            except Exception:
                provider_ips = [provider_ips]

        # Force codec safety: allow=ulaw,alaw only
        codecs_str = "ulaw,alaw"
        webhook_secret = settings.asterisk_webhook_secret or "your_shared_webhook_secret"
        transport_name = f"transport-{transport}"
 
        # 1. PJSIP config generation
        pjsip_lines = [
            f"; === SIP Trunk: {name} (ID: {trunk_id}) ==="
        ]
 
        if auth_type == "ip_auth":
            # IP Auth Endpoint
            pjsip_lines.extend([
                f"[provider-{trunk_id}-aor]",
                "type=aor",
                f"contact=sip:{sip_proxy}{port_suffix}",
                "",
                f"[provider-{trunk_id}]",
                "type=endpoint",
                f"transport={transport_name}",
                f"context=from-provider-{trunk_id}",
                "disallow=all",
                f"allow={codecs_str}",
                f"aors=provider-{trunk_id}-aor",
                "direct_media=no",
                "force_rport=yes",
                "rewrite_contact=yes",
                "rtp_symmetric=yes",
                "",
                f"[provider-{trunk_id}-identify]",
                "type=identify",
                f"endpoint=provider-{trunk_id}",
            ])
            for ip in provider_ips:
                if ip:
                    pjsip_lines.append(f"match={ip}")
            pjsip_lines.append("")
        else:
            # Username/Password Auth
            pjsip_lines.extend([
                f"[provider-{trunk_id}-auth]",
                "type=auth",
                "auth_type=userpass",
                f"username={username}",
                f"password={password}",
                "",
                f"[provider-{trunk_id}-aor]",
                "type=aor",
                f"contact=sip:{sip_proxy}{port_suffix}",
                "",
                f"[provider-{trunk_id}]",
                "type=endpoint",
                f"transport={transport_name}",
                f"context=from-provider-{trunk_id}",
                "disallow=all",
                f"allow={codecs_str}",
                f"outbound_auth=provider-{trunk_id}-auth",
                f"aors=provider-{trunk_id}-aor",
                f"from_user={username}",
                f"from_domain={sip_proxy}",
                "direct_media=no",
                "force_rport=yes",
                "rewrite_contact=yes",
                "rtp_symmetric=yes",
                "",
                f"[provider-{trunk_id}-reg]",
                "type=registration",
                f"transport={transport_name}",
                f"outbound_auth=provider-{trunk_id}-auth",
                f"client_uri=sip:{username}@{sip_proxy}{port_suffix}",
                f"server_uri=sip:{sip_proxy}{port_suffix}",
                f"contact_user={username}",
                ""
            ])
 
        pjsip_conf = "\n".join(pjsip_lines)
 
        base_api_url = settings.public_base_url or 'http://127.0.0.1:8000'
        # 2. Extensions config generation
        ext_lines = [
            f"; === Inbound Routing for Provider: {name} (ID: {trunk_id}) ===",
            f"[from-provider-{trunk_id}]",
            "",
            "; 1. Match numeric extensions",
            "exten => _X.,1,NoOp(Incoming SIP call from ${CALLERID(num)} to ${EXTEN})",
            " same => n,Set(CALL_UUID=${UUID()})",
            f" same => n,Set(CALL_PERMISSION=${{CURL({base_api_url}/api/webhooks/asterisk/inbound?caller_id=${{CALLERID(num)}}\&dialed_number=${{EXTEN}}\&call_uuid=${{CALL_UUID}}\&provider=asterisk\&secret={webhook_secret})}})",
            " same => n,GotoIf($[\"${CALL_PERMISSION:0:5}\"=\"ALLOW\"]?curl_ok_num:reject_num)",
            " same => n(reject_num),NoOp(Call rejected: ${CALL_PERMISSION})",
            " same => n,Hangup(21)",
            " same => n(curl_ok_num),Answer()",
            " same => n,AudioSocket(${CALL_UUID},127.0.0.1:9092)",
            " same => n,Hangup()",
            "",
            "; 2. Match numeric extensions with leading +",
            "exten => _+X.,1,NoOp(Incoming SIP call from ${CALLERID(num)} to ${EXTEN})",
            " same => n,Set(CALL_UUID=${UUID()})",
            f" same => n,Set(CALL_PERMISSION=${{CURL({base_api_url}/api/webhooks/asterisk/inbound?caller_id=${{CALLERID(num)}}\&dialed_number=${{EXTEN}}\&call_uuid=${{CALL_UUID}}\&provider=asterisk\&secret={webhook_secret})}})",
            " same => n,GotoIf($[\"${CALL_PERMISSION:0:5}\"=\"ALLOW\"]?curl_ok_plus:reject_plus)",
            " same => n(reject_plus),NoOp(Call rejected: ${CALL_PERMISSION})",
            " same => n,Hangup(21)",
            " same => n(curl_ok_plus),Answer()",
            " same => n,AudioSocket(${CALL_UUID},127.0.0.1:9092)",
            " same => n,Hangup()",
            "",
            "; 3. Match s extension (default routing)",
            "exten => s,1,NoOp(Incoming SIP call to s from ${CALLERID(num)})",
            " same => n,Set(CALL_UUID=${UUID()})",
            f" same => n,Set(CALL_PERMISSION=${{CURL({base_api_url}/api/webhooks/asterisk/inbound?caller_id=${{CALLERID(num)}}\&dialed_number=${{EXTEN}}\&call_uuid=${{CALL_UUID}}\&provider=asterisk\&secret={webhook_secret})}})",
            " same => n,GotoIf($[\"${CALL_PERMISSION:0:5}\"=\"ALLOW\"]?curl_ok_s:reject_s)",
            " same => n(reject_s),NoOp(Call rejected: ${CALL_PERMISSION})",
            " same => n,Hangup(21)",
            " same => n(curl_ok_s),Answer()",
            " same => n,AudioSocket(${CALL_UUID},127.0.0.1:9092)",
            " same => n,Hangup()",
        ]
        extensions_conf = "\n".join(ext_lines)


        # 3. Suggested firewall rules
        fw_rules = [
            f"# 1. Allow SIP traffic from SIP proxy ({sip_proxy})",
            f"sudo ufw allow from {sip_proxy} to any port {sip_port} proto {transport}",
        ]
        if auth_type == "ip_auth":
            for ip in provider_ips:
                if ip:
                    fw_rules.append(f"sudo ufw allow from {ip} to any port {sip_port} proto {transport}")
        fw_rules.extend([
            "# 2. Allow RTP media ports (typical default Asterisk RTP range)",
            "sudo ufw allow 10000:20000/udp"
        ])
        firewall_commands = "\n".join(fw_rules)

        # 4. Asterisk reload commands
        reload_commands = (
            "asterisk -rx \"pjsip reload\"\n"
            "asterisk -rx \"dialplan reload\""
        )

        return {
            "pjsip_conf": pjsip_conf,
            "extensions_conf": extensions_conf,
            "firewall_commands": firewall_commands,
            "reload_commands": reload_commands
        }


def validate_asterisk_config_syntax(pjsip_text: str, ext_text: str) -> Optional[str]:
    """Basic Python-side syntax sanity checker for Asterisk config files."""
    from typing import Optional
    for name, text in [("PJSIP", pjsip_text), ("Extensions", ext_text)]:
        open_brackets = text.count("[")
        close_brackets = text.count("]")
        if open_brackets != close_brackets:
            return f"{name} configuration has bracket mismatch: {open_brackets} open vs {close_brackets} close brackets."
            
        if name == "Extensions":
            for line in text.splitlines():
                line = line.strip()
                if line and not line.startswith(";") and not line.startswith("["):
                    if not (line.startswith("exten") or line.startswith("same") or line.startswith("include") or line.startswith("switch")):
                        return f"Invalid line format in Extensions: '{line}'"
    return None
