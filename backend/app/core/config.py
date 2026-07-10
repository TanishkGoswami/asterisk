from pydantic_settings import BaseSettings
from functools import lru_cache
from typing import Optional

class Settings(BaseSettings):
    # Supabase
    supabase_url: str
    supabase_anon_key: str
    supabase_jwt_secret: str
    supabase_service_role_key: Optional[str] = None
    voice_pilot_sso_secret: Optional[str] = None
    sip_encryption_key: Optional[str] = None

    
    # External APIs
    openai_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    deepgram_api_key: Optional[str] = None
    elevenlabs_api_key: Optional[str] = None
    sarvam_api_key: Optional[str] = None
    telephony_provider: str = "telnyx"
    telnyx_api_key: Optional[str] = None
    telnyx_account_sid: Optional[str] = None
    telnyx_connection_id: Optional[str] = None
    telnyx_webhook_url: Optional[str] = None
    telnyx_phone_number: Optional[str] = None
    twilio_account_sid: Optional[str] = None
    twilio_auth_token: Optional[str] = None
    twilio_webhook_url: Optional[str] = None
    twilio_phone_number: Optional[str] = None
    local_agent_knowledge_base_path: Optional[str] = None
    public_base_url: Optional[str] = None
    
    # Billing / Cost settings
    usd_to_inr: float = 83.5
    deepgram_stt_per_hour_usd: float = 0.72
    openai_input_per_1m_usd: float = 0.50     # GPT-3.5 input token price per 1M (0.50 USD)
    openai_output_per_1m_usd: float = 1.50    # GPT-3.5 output token price per 1M (1.50 USD)
    sarvam_tts_per_10k_chars_inr: float = 1.0
    credit_value_inr: float = 1.0
    twilio_outbound_per_min_usd: float = 0.013
    
    # Asterisk AudioSocket
    asterisk_audiosocket_enabled: bool = True
    asterisk_audiosocket_host: str = "127.0.0.1"
    asterisk_audiosocket_port: int = 9092
    asterisk_webhook_secret: Optional[str] = None
    asterisk_provider_name: str = "airtel_or_jio"
    asterisk_default_sample_rate: int = 8000
    asterisk_vps_url: Optional[str] = None          # e.g. http://72.60.202.148:8010
    asterisk_ssh_host: str = "72.60.202.148"
    asterisk_ssh_user: str = "root"
    asterisk_ssh_key_path: Optional[str] = None     # path to SSH private key if needed
    asterisk_mode: str = "local"
    use_ssh_for_asterisk: bool = False
    asterisk_cli_command: str = "asterisk"
    asterisk_test_beep_on_connect: bool = False  # Send 440Hz beep on connect to verify AudioSocket framing
    
    # Redis
    redis_url: str = "redis://localhost:6379/0"
    
    # Celery
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"
    
    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_workers: int = 4
    
    # App
    environment: str = "development"
    log_level: str = "INFO"
    debug: bool = False

    # Telephony kill switches
    OUTBOUND_CALLS_ENABLED: bool = False
    BATCH_CALLS_ENABLED: bool = False
    TWILIO_SIP_TRUNK_ENABLED: bool = False
    REAL_DIALING_ENABLED: bool = False
    
    # Streaming TTS Chunker Configs
    STREAMING_TTS_MODE: str = "safe_sentence"
    ADVANCED_CHUNKER: bool = False
    PUNCTUATION_RESTORE: bool = False
    FIRST_CHUNK_TIMEOUT_MS: int = 0
    NEXT_CHUNK_TIMEOUT_MS: int = 1200
    DISABLE_STREAMING_TTS: bool = True
    TTS_PREBUFFER_MS: int = 1500
    MIN_AUDIO_CHUNKS_BEFORE_PLAYBACK: int = 2

    # Limits
    call_timeout_seconds: int = 3600  # 1 hour
    inactivity_timeout_seconds: int = 30
    max_concurrent_calls_per_workspace: int = 100
    max_message_history_size: int = 50

    # Latency targets
    stt_timeout_seconds: float = 3.0
    llm_timeout_seconds: float = 4.0
    tts_timeout_seconds: float = 5.0

    # Call Admission Control (CAC) Configs
    allow_calls_without_redis: bool = False
    default_workspace_max_concurrent_calls: int = 1
    default_agent_max_concurrent_calls: int = 1
    call_reservation_ttl_seconds: int = 7200
    call_usage_monitor_interval_seconds: int = 15
    block_overdue_workspaces: bool = True
    
    model_config = {
        "env_file": ".env",
        "case_sensitive": False,
        "env_prefix": "",
        "extra": "ignore"
    }

@lru_cache
def get_settings() -> Settings:
    return Settings()

settings = get_settings()
