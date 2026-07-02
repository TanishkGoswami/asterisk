# routers/diagnostics.py
"""
Asterisk Call Flow Diagnostics Endpoint
Returns real-time health status of AudioSocket, sessions, and configuration
"""

import asyncio
from datetime import datetime, timezone
from typing import Dict, List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import logging
import socket
import subprocess
from enum import Enum

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/asterisk", tags=["diagnostics"])

# ============================================================================
# Data Models
# ============================================================================

class AudioSocketConfigModel(BaseModel):
    enabled: bool
    host: str
    port: int
    timeout_seconds: int
    audio_format: str
    audio_sample_rate: int


class AudioSocketRuntimeModel(BaseModel):
    listening: bool
    listening_address: str
    accepting_connections: bool
    active_sessions: int
    total_sessions_handled: int
    uptime_seconds: int


class ActiveSessionModel(BaseModel):
    session_uuid: str
    direction: str  # "inbound" or "outbound"
    state: str  # "greeting", "listening", "processing", "responding"
    caller: Optional[str] = None
    callee: Optional[str] = None
    agent_id: Optional[str] = None
    connected_at: datetime
    audio_bytes_sent: int
    audio_bytes_received: int
    last_activity: datetime


class VPSConnectionModel(BaseModel):
    vps_url: str
    reachable: bool
    latency_ms: Optional[int] = None
    last_check: datetime


class SSHTunnelModel(BaseModel):
    expected: bool
    required_for_mode: bool
    command: str


class DialplanChecksModel(BaseModel):
    inbound_dialplan_exists: bool
    inbound_uses_audiosocket: bool
    inbound_correct_host_port: bool
    outbound_dialplan_exists: bool
    outbound_uses_audiosocket: bool
    outbound_correct_host_port: bool
    dialplan_last_verified: datetime


class TTSGenerationStatusModel(BaseModel):
    timestamp: datetime
    status: str  # "success", "timeout", "error"
    provider: str
    duration_ms: int
    output_bytes: int
    text: str
    error_message: Optional[str] = None


class AudioSendStatusModel(BaseModel):
    timestamp: datetime
    status: str  # "success", "error", "partial"
    chunks_sent: int
    bytes_sent: int
    duration_ms: int
    error_message: Optional[str] = None


class CallDropModel(BaseModel):
    timestamp: datetime
    reason: str  # "call_ended", "barge_in", "timeout", "error", "unknown"
    session_uuid: str
    duration_seconds: int


class ErrorModel(BaseModel):
    severity: str  # "error", "warning"
    component: str
    message: str
    timestamp: datetime
    affected_sessions: int
    recovery_attempted: bool


class RecentMetricsModel(BaseModel):
    last_inbound_connect: Optional[datetime] = None
    last_outbound_connect: Optional[datetime] = None
    last_tts_generation: Optional[TTSGenerationStatusModel] = None
    last_audio_send: Optional[AudioSendStatusModel] = None
    last_call_drop: Optional[CallDropModel] = None


class CallFlowDiagnosticsResponse(BaseModel):
    timestamp: datetime
    mode: str  # "vps", "local"
    status: str  # "operational", "degraded", "down"
    
    audiosocket_config: AudioSocketConfigModel
    audiosocket_runtime: AudioSocketRuntimeModel
    active_sessions: List[ActiveSessionModel]
    vps_connection: VPSConnectionModel
    ssh_tunnel: SSHTunnelModel
    dialplan_checks: DialplanChecksModel
    recent_metrics: RecentMetricsModel
    detected_errors: List[ErrorModel]
    recommendations: List[str]


# ============================================================================
# Global State Tracking
# ============================================================================

class DiagnosticsState:
    """Singleton to track diagnostic metrics"""
    
    def __init__(self):
        self.audiosocket_start_time: Optional[datetime] = None
        self.total_sessions_handled = 0
        self.active_sessions: Dict[str, Dict] = {}
        self.errors: List[ErrorModel] = []
        self.last_tts_generation: Optional[TTSGenerationStatusModel] = None
        self.last_audio_send: Optional[AudioSendStatusModel] = None
        self.last_call_drop: Optional[CallDropModel] = None
        self.last_inbound_connect: Optional[datetime] = None
        self.last_outbound_connect: Optional[datetime] = None
    
    def add_error(self, severity: str, component: str, message: str, affected_sessions: int = 1):
        """Log an error for diagnostics"""
        error = ErrorModel(
            severity=severity,
            component=component,
            message=message,
            timestamp=datetime.now(timezone.utc),
            affected_sessions=affected_sessions,
            recovery_attempted=False
        )
        self.errors.append(error)
        # Keep only last 100 errors
        if len(self.errors) > 100:
            self.errors = self.errors[-100:]
        logger.error(f"[DIAGNOSTICS] {severity.upper()} - {component}: {message}")
    
    def record_session_start(self, session_uuid: str, direction: str, caller: Optional[str] = None, 
                            callee: Optional[str] = None, agent_id: Optional[str] = None):
        """Record new session"""
        self.active_sessions[session_uuid] = {
            "direction": direction,
            "state": "greeting",
            "caller": caller,
            "callee": callee,
            "agent_id": agent_id,
            "connected_at": datetime.now(timezone.utc),
            "audio_bytes_sent": 0,
            "audio_bytes_received": 0,
            "last_activity": datetime.now(timezone.utc)
        }
        
        if direction == "inbound":
            self.last_inbound_connect = datetime.now(timezone.utc)
        elif direction == "outbound":
            self.last_outbound_connect = datetime.now(timezone.utc)
        
        logger.info(f"[DIAGNOSTICS] Session started: {session_uuid} ({direction})")
    
    def record_session_end(self, session_uuid: str, drop_reason: str = "call_ended"):
        """Record session completion"""
        if session_uuid in self.active_sessions:
            session = self.active_sessions[session_uuid]
            duration = (datetime.now(timezone.utc) - session["connected_at"]).total_seconds()
            
            self.last_call_drop = CallDropModel(
                timestamp=datetime.now(timezone.utc),
                reason=drop_reason,
                session_uuid=session_uuid,
                duration_seconds=int(duration)
            )
            
            del self.active_sessions[session_uuid]
            self.total_sessions_handled += 1
            logger.info(f"[DIAGNOSTICS] Session ended: {session_uuid} ({drop_reason}, {duration:.1f}s)")
    
    def update_session_state(self, session_uuid: str, state: str, audio_sent: int = 0, audio_received: int = 0):
        """Update session runtime state"""
        if session_uuid in self.active_sessions:
            self.active_sessions[session_uuid]["state"] = state
            self.active_sessions[session_uuid]["audio_bytes_sent"] += audio_sent
            self.active_sessions[session_uuid]["audio_bytes_received"] += audio_received
            self.active_sessions[session_uuid]["last_activity"] = datetime.now(timezone.utc)
    
    def record_tts_generation(self, status: str, provider: str, duration_ms: int, 
                             output_bytes: int, text: str, error_message: Optional[str] = None):
        """Record TTS generation event"""
        self.last_tts_generation = TTSGenerationStatusModel(
            timestamp=datetime.now(timezone.utc),
            status=status,
            provider=provider,
            duration_ms=duration_ms,
            output_bytes=output_bytes,
            text=text,
            error_message=error_message
        )
        logger.info(f"[DIAGNOSTICS] TTS: {status} ({provider}, {duration_ms}ms, {output_bytes} bytes)")
    
    def record_audio_send(self, status: str, chunks_sent: int, bytes_sent: int, 
                         duration_ms: int, error_message: Optional[str] = None):
        """Record audio transmission event"""
        self.last_audio_send = AudioSendStatusModel(
            timestamp=datetime.now(timezone.utc),
            status=status,
            chunks_sent=chunks_sent,
            bytes_sent=bytes_sent,
            duration_ms=duration_ms,
            error_message=error_message
        )
        logger.info(f"[DIAGNOSTICS] Audio send: {status} ({chunks_sent} chunks, {bytes_sent} bytes)")


# Global instance
diagnostics = DiagnosticsState()


# ============================================================================
# Helper Functions
# ============================================================================

def check_audiosocket_listening(host: str, port: int) -> bool:
    """Check if AudioSocket is listening on configured host:port"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2)
        result = sock.connect_ex((host, port))
        sock.close()
        return result == 0
    except Exception as e:
        logger.error(f"[DIAGNOSTICS] Failed to check AudioSocket: {e}")
        return False


def check_vps_connectivity(vps_url: str) -> tuple[bool, Optional[int]]:
    """Check if VPS backend is reachable and measure latency"""
    try:
        import time
        import requests
        
        start = time.time()
        response = requests.get(f"{vps_url}/health", timeout=5)
        latency_ms = int((time.time() - start) * 1000)
        
        return response.status_code == 200, latency_ms
    except Exception as e:
        logger.warning(f"[DIAGNOSTICS] VPS not reachable: {e}")
        return False, None


def check_ssh_tunnel() -> bool:
    """Check if SSH reverse tunnel is active"""
    try:
        # Try to connect to localhost:9092 through SSH tunnel
        result = subprocess.run(
            ["ssh", "root@72.60.202.148", "curl", "-s", "http://127.0.0.1:9092/health"],
            timeout=5,
            capture_output=True
        )
        return result.returncode == 0
    except Exception as e:
        logger.warning(f"[DIAGNOSTICS] SSH tunnel check failed: {e}")
        return False


def verify_inbound_dialplan() -> tuple[bool, bool, bool]:
    """Verify inbound dialplan on VPS Asterisk"""
    try:
        result = subprocess.run(
            ["ssh", "root@72.60.202.148", "asterisk", "-r", "-x", "dialplan show"],
            timeout=10,
            capture_output=True,
            text=True
        )
        
        output = result.stdout
        has_dialplan = "inbound" in output.lower()
        uses_audiosocket = "audiosocket" in output.lower()
        correct_config = "127.0.0.1" in output and "9092" in output
        
        return has_dialplan, uses_audiosocket, correct_config
    except Exception as e:
        logger.warning(f"[DIAGNOSTICS] Inbound dialplan check failed: {e}")
        return False, False, False


def verify_outbound_dialplan() -> tuple[bool, bool, bool]:
    """Verify outbound dialplan on VPS Asterisk"""
    try:
        result = subprocess.run(
            ["ssh", "root@72.60.202.148", "asterisk", "-r", "-x", "dialplan show"],
            timeout=10,
            capture_output=True,
            text=True
        )
        
        output = result.stdout
        has_dialplan = "outbound" in output.lower()
        uses_audiosocket = "audiosocket" in output.lower()
        correct_config = "127.0.0.1" in output and "9092" in output
        
        return has_dialplan, uses_audiosocket, correct_config
    except Exception as e:
        logger.warning(f"[DIAGNOSTICS] Outbound dialplan check failed: {e}")
        return False, False, False


# ============================================================================
# Endpoint
# ============================================================================

@router.get("/call-flow-diagnostics", response_model=CallFlowDiagnosticsResponse)
async def get_call_flow_diagnostics(
    from_config=None  # Inject config from FastAPI dependency
) -> CallFlowDiagnosticsResponse:
    """
    Comprehensive diagnostics endpoint for Asterisk + AudioSocket + FastAPI integration.
    
    Returns current configuration, runtime state, active sessions, and detected issues.
    """
    
    # Get configuration (would be from FastAPI dependency in real implementation)
    from config import (
        ASTERISK_MODE,
        ASTERISK_VPS_URL,
        ASTERISK_AUDIOSOCKET_ENABLED,
        ASTERISK_AUDIOSOCKET_HOST,
        ASTERISK_AUDIOSOCKET_PORT,
        ASTERISK_AUDIOSOCKET_TIMEOUT,
        AUDIO_FORMAT,
        AUDIO_SAMPLE_RATE
    )
    
    now = datetime.now(timezone.utc)
    recommendations: List[str] = []
    detected_errors: List[ErrorModel] = []
    
    # ========================================================================
    # 1. AudioSocket Configuration & Runtime
    # ========================================================================
    
    config = AudioSocketConfigModel(
        enabled=ASTERISK_AUDIOSOCKET_ENABLED,
        host=ASTERISK_AUDIOSOCKET_HOST,
        port=ASTERISK_AUDIOSOCKET_PORT,
        timeout_seconds=ASTERISK_AUDIOSOCKET_TIMEOUT,
        audio_format=AUDIO_FORMAT,
        audio_sample_rate=AUDIO_SAMPLE_RATE
    )
    
    # Check if listening
    listening = check_audiosocket_listening(
        ASTERISK_AUDIOSOCKET_HOST,
        ASTERISK_AUDIOSOCKET_PORT
    )
    
    uptime_seconds = 0
    if diagnostics.audiosocket_start_time:
        uptime_seconds = int((now - diagnostics.audiosocket_start_time).total_seconds())
    
    runtime = AudioSocketRuntimeModel(
        listening=listening,
        listening_address=f"{ASTERISK_AUDIOSOCKET_HOST}:{ASTERISK_AUDIOSOCKET_PORT}",
        accepting_connections=listening,
        active_sessions=len(diagnostics.active_sessions),
        total_sessions_handled=diagnostics.total_sessions_handled,
        uptime_seconds=uptime_seconds
    )
    
    if not listening and ASTERISK_AUDIOSOCKET_ENABLED:
        detected_errors.append(ErrorModel(
            severity="error",
            component="audiosocket",
            message=f"Not listening on {ASTERISK_AUDIOSOCKET_HOST}:{ASTERISK_AUDIOSOCKET_PORT}",
            timestamp=now,
            affected_sessions=len(diagnostics.active_sessions),
            recovery_attempted=False
        ))
        recommendations.append(
            f"AudioSocket not listening on {ASTERISK_AUDIOSOCKET_HOST}:{ASTERISK_AUDIOSOCKET_PORT}. "
            f"Check if backend is running and .env has ASTERISK_AUDIOSOCKET_ENABLED=true"
        )
    
    # ========================================================================
    # 2. Active Sessions
    # ========================================================================
    
    active_sessions = [
        ActiveSessionModel(
            session_uuid=uuid,
            direction=session["direction"],
            state=session["state"],
            caller=session.get("caller"),
            callee=session.get("callee"),
            agent_id=session.get("agent_id"),
            connected_at=session["connected_at"],
            audio_bytes_sent=session["audio_bytes_sent"],
            audio_bytes_received=session["audio_bytes_received"],
            last_activity=session["last_activity"]
        )
        for uuid, session in diagnostics.active_sessions.items()
    ]
    
    # ========================================================================
    # 3. VPS Connectivity
    # ========================================================================
    
    vps_reachable, vps_latency = check_vps_connectivity(ASTERISK_VPS_URL)
    
    vps_connection = VPSConnectionModel(
        vps_url=ASTERISK_VPS_URL,
        reachable=vps_reachable,
        latency_ms=vps_latency,
        last_check=now
    )
    
    if ASTERISK_MODE == "vps" and not vps_reachable:
        detected_errors.append(ErrorModel(
            severity="warning",
            component="vps_connection",
            message=f"VPS backend at {ASTERISK_VPS_URL} not reachable",
            timestamp=now,
            affected_sessions=len(diagnostics.active_sessions),
            recovery_attempted=False
        ))
        recommendations.append(
            f"Cannot reach VPS backend at {ASTERISK_VPS_URL}. "
            f"Verify VPS is running and network connectivity."
        )
    
    # ========================================================================
    # 4. SSH Tunnel
    # ========================================================================
    
    tunnel_expected = ASTERISK_MODE == "vps"
    ssh_tunnel = SSHTunnelModel(
        expected=tunnel_expected,
        required_for_mode=ASTERISK_MODE == "vps",
        command="ssh -N -R 9092:127.0.0.1:9092 root@72.60.202.148"
    )
    
    if tunnel_expected:
        tunnel_active = check_ssh_tunnel()
        if not tunnel_active:
            detected_errors.append(ErrorModel(
                severity="error",
                component="ssh_tunnel",
                message="SSH reverse tunnel not responding",
                timestamp=now,
                affected_sessions=len(diagnostics.active_sessions),
                recovery_attempted=False
            ))
            recommendations.append(
                "SSH tunnel is inactive. Re-establish with: "
                "ssh -N -R 9092:127.0.0.1:9092 root@72.60.202.148"
            )
    
    # ========================================================================
    # 5. Dialplan Checks
    # ========================================================================
    
    inbound_exists, inbound_audiosocket, inbound_correct = verify_inbound_dialplan()
    outbound_exists, outbound_audiosocket, outbound_correct = verify_outbound_dialplan()
    
    dialplan_checks = DialplanChecksModel(
        inbound_dialplan_exists=inbound_exists,
        inbound_uses_audiosocket=inbound_audiosocket,
        inbound_correct_host_port=inbound_correct,
        outbound_dialplan_exists=outbound_exists,
        outbound_uses_audiosocket=outbound_audiosocket,
        outbound_correct_host_port=outbound_correct,
        dialplan_last_verified=now
    )
    
    if not inbound_audiosocket:
        recommendations.append(
            "Inbound dialplan does not route to AudioSocket. "
            "Add to dialplan: exten => X.,n,Set(CHANNEL(audiosocket)=127.0.0.1:9092)"
        )
    
    if not outbound_audiosocket:
        recommendations.append(
            "Outbound dialplan does not route to AudioSocket. "
            "Verify outbound context has AudioSocket() exten"
        )
    
    # ========================================================================
    # 6. Recent Metrics
    # ========================================================================
    
    recent_metrics = RecentMetricsModel(
        last_inbound_connect=diagnostics.last_inbound_connect,
        last_outbound_connect=diagnostics.last_outbound_connect,
        last_tts_generation=diagnostics.last_tts_generation,
        last_audio_send=diagnostics.last_audio_send,
        last_call_drop=diagnostics.last_call_drop
    )
    
    if diagnostics.last_tts_generation and diagnostics.last_tts_generation.status == "error":
        recommendations.append(
            f"Last TTS generation failed: {diagnostics.last_tts_generation.error_message}. "
            f"Check TTS service credentials and connectivity."
        )
    
    if diagnostics.last_audio_send and diagnostics.last_audio_send.status == "error":
        recommendations.append(
            f"Last audio send failed: {diagnostics.last_audio_send.error_message}. "
            f"Check AudioSocket socket and network."
        )
    
    # ========================================================================
    # 7. Overall Status
    # ========================================================================
    
    if not listening or not vps_reachable:
        overall_status = "down"
    elif len(detected_errors) > 0:
        overall_status = "degraded"
    else:
        overall_status = "operational"
    
    # ========================================================================
    # 8. Build Response
    # ========================================================================
    
    response = CallFlowDiagnosticsResponse(
        timestamp=now,
        mode=ASTERISK_MODE,
        status=overall_status,
        audiosocket_config=config,
        audiosocket_runtime=runtime,
        active_sessions=active_sessions,
        vps_connection=vps_connection,
        ssh_tunnel=ssh_tunnel,
        dialplan_checks=dialplan_checks,
        recent_metrics=recent_metrics,
        detected_errors=detected_errors[:20],  # Limit to 20 most recent
        recommendations=recommendations
    )
    
    logger.info(f"[DIAGNOSTICS] Request completed: status={overall_status}, "
                f"sessions={len(active_sessions)}, errors={len(detected_errors)}")
    
    return response


# ============================================================================
# Health Check Endpoint
# ============================================================================

@router.get("/health")
async def health_check():
    """Simple health check for backward compatibility"""
    return {
        "status": "ok",
        "mode": "vps",
        "audiosocket_listening": check_audiosocket_listening(
            "127.0.0.1", 9092
        )
    }
