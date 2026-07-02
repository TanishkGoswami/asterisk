# app/core/logging_config.py
"""
Enhanced structured logging for Asterisk + AudioSocket + FastAPI integration.
Captures detailed lifecycle events for debugging.
"""

import logging
import logging.handlers
import os
import sys
import traceback
from datetime import datetime
from typing import Optional, Dict, Any

# ============================================================================
# Structured Logger Wrapper
# ============================================================================

class StructuredLogger:
    """
    Wrapper around standard logger providing structured, contextual logging.
    Logs AudioSocket lifecycle with consistent formatting.
    """
    
    def __init__(self, name: str):
        self.logger = logging.getLogger(name)
        self._context: Dict[str, Any] = {}
    
    def set_context(self, **kwargs):
        """Set context variables that will be included in all logs"""
        self._context.update(kwargs)
    
    def clear_context(self):
        """Clear context"""
        self._context = {}
    
    def _format_context(self) -> str:
        """Format context dict for log output"""
        if not self._context:
            return ""
        
        items = [f"{k}={v}" for k, v in self._context.items()]
        return f" [{', '.join(items)}]"
        
    def info(self, msg: str, *args, **kwargs):
        """Standard info logging delegation"""
        self.logger.info(msg + self._format_context(), *args, **kwargs)

    def debug(self, msg: str, *args, **kwargs):
        """Standard debug logging delegation"""
        self.logger.debug(msg + self._format_context(), *args, **kwargs)

    def warning(self, msg: str, *args, **kwargs):
        """Standard warning logging delegation"""
        self.logger.warning(msg + self._format_context(), *args, **kwargs)

    def error(self, msg: str, *args, **kwargs):
        """Standard error logging delegation"""
        self.logger.error(msg + self._format_context(), *args, **kwargs)
    
    # ========================================================================
    # AudioSocket Server Lifecycle
    # ========================================================================
    
    def audiosocket_server_started(self, host: str, port: int):
        """Log: AudioSocket server started"""
        msg = f"AudioSocket server started on {host}:{port}"
        self.logger.info(msg + self._format_context())
    
    def audiosocket_connection_accepted(self, client_addr: str, client_port: int):
        """Log: Connection accepted"""
        msg = f"AudioSocket connection accepted from {client_addr}:{client_port}"
        self.logger.debug(msg + self._format_context())
    
    def audiosocket_connection_closed(self, reason: str, duration_ms: Optional[int] = None):
        """Log: Connection closed"""
        duration_str = f", duration={duration_ms}ms" if duration_ms else ""
        msg = f"AudioSocket connection closed: reason={reason}{duration_str}"
        self.logger.info(msg + self._format_context())
    
    def audiosocket_connection_error(self, error: Exception, operation: str = ""):
        """Log: Connection error with traceback"""
        msg = f"AudioSocket connection error during {operation}"
        self.logger.error(msg + self._format_context())
        self.logger.error(f"Exception: {type(error).__name__}: {str(error)}")
        self.logger.debug(traceback.format_exc())
    
    # ========================================================================
    # UUID & Session Handshake
    # ========================================================================
    
    def uuid_read_started(self, expected_bytes: int = 36):
        """Log: Starting UUID read"""
        msg = f"UUID handshake started (expecting {expected_bytes} bytes)"
        self.logger.debug(msg + self._format_context())
    
    def uuid_received(self, uuid: str):
        """Log: UUID successfully received"""
        msg = f"UUID received: {uuid}"
        self.logger.info(msg + self._format_context())
    
    def uuid_invalid(self, received_bytes: int, expected_bytes: int = 36):
        """Log: Invalid UUID format"""
        msg = f"UUID invalid: received {received_bytes} bytes, expected {expected_bytes}"
        self.logger.error(msg + self._format_context())
    
    # ========================================================================
    # Call Direction Detection
    # ========================================================================
    
    def call_direction_detected(self, direction: str):
        """Log: Call direction determined (inbound/outbound)"""
        msg = f"Call direction detected: {direction.upper()}"
        self.logger.info(msg + self._format_context())
    
    def session_created(self, session_id: str, direction: str):
        """Log: Session created in database"""
        msg = f"Session created: {session_id} ({direction})"
        self.logger.info(msg + self._format_context())
    
    def caller_info(self, caller: Optional[str], callee: Optional[str], agent_id: Optional[str]):
        """Log: Caller/callee info"""
        msg = f"Caller: {caller}, Callee: {callee}, Agent: {agent_id}"
        self.logger.debug(msg + self._format_context())
    
    # ========================================================================
    # AI Pipeline Initialization
    # ========================================================================
    
    def ai_pipeline_initializing(self):
        """Log: AI pipeline startup"""
        msg = "Initializing AI pipeline..."
        self.logger.debug(msg + self._format_context())
    
    def agent_loaded(self, agent_id: str, agent_name: Optional[str] = None):
        """Log: Agent loaded from database"""
        name_str = f" ({agent_name})" if agent_name else ""
        msg = f"Agent loaded: {agent_id}{name_str}"
        self.logger.info(msg + self._format_context())
    
    def agent_not_found(self, agent_id: str):
        """Log: Agent lookup failed"""
        msg = f"Agent not found: {agent_id}"
        self.logger.error(msg + self._format_context())
    
    # ========================================================================
    # TTS (Text-to-Speech)
    # ========================================================================
    
    def greeting_generation_started(self, text: str):
        """Log: TTS greeting generation started"""
        msg = f"Generating greeting: \"{text[:100]}...\""
        self.logger.info(msg + self._format_context())
    
    def tts_request_initiated(self, provider: str, text: str, timeout_s: int):
        """Log: TTS API request initiated"""
        msg = f"TTS request: provider={provider}, timeout={timeout_s}s, text_len={len(text)}"
        self.logger.debug(msg + self._format_context())
    
    def tts_completed(self, duration_ms: int, output_bytes: int, audio_format: str = "slin16"):
        """Log: TTS completed successfully"""
        msg = f"TTS completed: {duration_ms}ms, {output_bytes} bytes ({audio_format})"
        self.logger.info(msg + self._format_context())
    
    def tts_timeout(self, timeout_s: int):
        """Log: TTS timeout"""
        msg = f"TTS timeout after {timeout_s}s"
        self.logger.error(msg + self._format_context())
    
    def tts_error(self, error: Exception):
        """Log: TTS error"""
        msg = f"TTS error: {type(error).__name__}: {str(error)}"
        self.logger.error(msg + self._format_context())
        self.logger.debug(traceback.format_exc())
    
    # ========================================================================
    # Audio Transmission
    # ========================================================================
    
    def audio_stream_started(self, total_bytes: int, chunk_size: int = 2048):
        """Log: Audio streaming started"""
        msg = f"Starting audio stream: {total_bytes} bytes total, {chunk_size} bytes/chunk"
        self.logger.debug(msg + self._format_context())
    
    def audio_chunk_sent(self, chunk_num: int, offset: int, bytes_sent: int, cumulative: int):
        """Log: Audio chunk sent"""
        msg = f"Audio chunk {chunk_num}: offset={offset}, bytes={bytes_sent}, cumulative={cumulative}"
        self.logger.debug(msg + self._format_context())
    
    def audio_stream_completed(self, total_chunks: int, total_bytes: int, duration_ms: int):
        """Log: Audio stream completed"""
        msg = f"Audio stream completed: {total_chunks} chunks, {total_bytes} bytes, {duration_ms}ms"
        self.logger.info(msg + self._format_context())
    
    def audio_stream_interrupted(self, reason: str, bytes_sent: int):
        """Log: Audio stream interrupted (e.g., barge-in)"""
        msg = f"Audio stream interrupted: {reason}, {bytes_sent} bytes sent before interrupt"
        self.logger.info(msg + self._format_context())
    
    def audio_send_error(self, error: Exception, bytes_sent: int):
        """Log: Error sending audio"""
        msg = f"Audio send error after {bytes_sent} bytes: {type(error).__name__}"
        self.logger.error(msg + self._format_context())
        self.logger.error(f"Exception: {str(error)}")
        self.logger.debug(traceback.format_exc())
    
    # ========================================================================
    # Speech Recognition (STT)
    # ========================================================================
    
    def input_waiting(self):
        """Log: Waiting for caller input"""
        msg = "Waiting for audio input from caller..."
        self.logger.debug(msg + self._format_context())
    
    def audio_input_received(self, bytes_count: int):
        """Log: Audio input from caller received"""
        msg = f"Audio input detected from caller: {bytes_count} bytes"
        self.logger.debug(msg + self._format_context())
    
    def stt_request_initiated(self, provider: str, audio_bytes: int):
        """Log: Speech-to-text request started"""
        msg = f"STT request: provider={provider}, audio={audio_bytes} bytes"
        self.logger.debug(msg + self._format_context())
    
    def transcript_interim(self, text: str, confidence: Optional[float] = None):
        """Log: Interim transcript"""
        conf_str = f" (confidence={confidence:.2f})" if confidence else ""
        msg = f"Transcript (interim): \"{text}\"{conf_str}"
        self.logger.debug(msg + self._format_context())
    
    def transcript_final(self, text: str, confidence: float, latency_ms: int):
        """Log: Final transcript"""
        msg = f"Transcript (final): \"{text}\" (confidence={confidence:.2f}, latency={latency_ms}ms)"
        self.logger.info(msg + self._format_context())
    
    def barge_in_triggered(self):
        """Log: Caller interrupted greeting"""
        msg = "Barge-in triggered: caller interrupted greeting"
        self.logger.info(msg + self._format_context())
    
    # ========================================================================
    # LLM Processing
    # ========================================================================
    
    def llm_request_initiated(self, model: str, transcript: str):
        """Log: LLM request started"""
        msg = f"LLM request: model={model}, transcript=\"{transcript[:80]}...\""
        self.logger.debug(msg + self._format_context())
    
    def llm_response_received(self, text: str, latency_ms: int, tokens_used: Optional[int] = None):
        """Log: LLM response received"""
        tokens_str = f", tokens={tokens_used}" if tokens_used else ""
        msg = f"LLM response: \"{text[:80]}...\" (latency={latency_ms}ms{tokens_str})"
        self.logger.info(msg + self._format_context())
    
    def llm_timeout(self, timeout_s: int):
        """Log: LLM timeout"""
        msg = f"LLM timeout after {timeout_s}s"
        self.logger.error(msg + self._format_context())
    
    def llm_error(self, error: Exception):
        """Log: LLM error"""
        msg = f"LLM error: {type(error).__name__}: {str(error)}"
        self.logger.error(msg + self._format_context())
        self.logger.debug(traceback.format_exc())
    
    # ========================================================================
    # Response Generation
    # ========================================================================
    
    def response_audio_generation_started(self, text: str):
        """Log: Response audio generation started"""
        msg = f"Generating response audio: \"{text[:100]}...\""
        self.logger.debug(msg + self._format_context())
    
    def response_audio_completed(self, bytes_count: int, duration_ms: int):
        """Log: Response audio generation completed"""
        msg = f"Response audio completed: {bytes_count} bytes, {duration_ms}ms"
        self.logger.info(msg + self._format_context())
    
    def response_audio_sent(self, chunks: int, bytes_count: int, duration_ms: int):
        """Log: Response audio sent to caller"""
        msg = f"Response audio sent: {chunks} chunks, {bytes_count} bytes, {duration_ms}ms"
        self.logger.info(msg + self._format_context())
    
    # ========================================================================
    # Call State Machine
    # ========================================================================
    
    def call_state_changed(self, from_state: str, to_state: str):
        """Log: Call state transition"""
        msg = f"Call state: {from_state} → {to_state}"
        self.logger.debug(msg + self._format_context())
    
    def call_duration_logged(self, duration_seconds: float, turn_count: int):
        """Log: Call duration at completion"""
        msg = f"Call completed: {duration_seconds:.1f}s, {turn_count} turns"
        self.logger.info(msg + self._format_context())
    
    # ========================================================================
    # Errors & Recovery
    # ========================================================================
    
    def error_detected(self, component: str, error: Exception, severity: str = "error"):
        """Log: Component error"""
        msg = f"{severity.upper()}: {component} - {type(error).__name__}: {str(error)}"
        if severity == "error":
            self.logger.error(msg + self._format_context())
        else:
            self.logger.warning(msg + self._format_context())
        self.logger.debug(traceback.format_exc())
    
    def recovery_attempted(self, action: str, details: str = ""):
        """Log: Recovery action attempted"""
        msg = f"Recovery: {action}"
        if details:
            msg += f" - {details}"
        self.logger.info(msg + self._format_context())


# ============================================================================
# Logger Factory
# ============================================================================

def get_structured_logger(name: str) -> StructuredLogger:
    """Get a structured logger instance"""
    return StructuredLogger(name)


# ============================================================================
# Logging Configuration Setup
# ============================================================================

def setup_logging(log_level: str = "DEBUG", log_file: Optional[str] = None):
    """
    Configure logging system with both console and file handlers.
    
    Args:
        log_level: DEBUG, INFO, WARNING, ERROR
        log_file: Optional file path for log output
    """
    
    # Convert string level to logging level
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)
    
    # Create formatters
    detailed_format = (
        "%(asctime)s | %(levelname)-8s | %(name)s:%(lineno)d | %(message)s"
    )
    simple_format = "%(levelname)-8s | %(message)s"
    
    # Console handler (simple format)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(numeric_level)
    console_formatter = logging.Formatter(simple_format)
    console_handler.setFormatter(console_formatter)
    
    # File handler (detailed format)
    if log_file:
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=10 * 1024 * 1024,  # 10MB
            backupCount=10
        )
        file_handler.setLevel(logging.DEBUG)  # Always log debug to file
        file_formatter = logging.Formatter(detailed_format)
        file_handler.setFormatter(file_formatter)
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    
    # Add handlers
    root_logger.addHandler(console_handler)
    if log_file:
        root_logger.addHandler(file_handler)
    
    # Suppress noisy third-party loggers
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    
    root_logger.info(f"Logging configured: level={log_level}, file={log_file}")
