import logging
import math
from app.core.config import settings

logger = logging.getLogger(__name__)

def calculate_provider_costs(
    duration_seconds: float,
    twilio_billable_minutes: float = None,
    stt_audio_seconds: float = None,
    llm_input_tokens: int = 0,
    llm_output_tokens: int = 0,
    tts_characters: int = 0,
    twilio_cost_inr: float = 0.0,
    twilio_cost_source: str = "estimated",
    usd_to_inr: float = None,
    deepgram_per_hour_usd: float = None,
    openai_input_per_1m_usd: float = None,
    openai_output_per_1m_usd: float = None,
    sarvam_per_10k_chars_inr: float = None,
    credit_value_inr: float = None,
    twilio_fallback_per_min_usd: float = None,
    **kwargs
) -> dict:
    try:
        # Load defaults from settings if not passed
        u_to_i = usd_to_inr if usd_to_inr is not None else settings.usd_to_inr
        dg_usd = deepgram_per_hour_usd if deepgram_per_hour_usd is not None else settings.deepgram_stt_per_hour_usd
        llm_in_usd = openai_input_per_1m_usd if openai_input_per_1m_usd is not None else settings.openai_input_per_1m_usd
        llm_out_usd = openai_output_per_1m_usd if openai_output_per_1m_usd is not None else settings.openai_output_per_1m_usd
        sarvam_inr = sarvam_per_10k_chars_inr if sarvam_per_10k_chars_inr is not None else settings.sarvam_tts_per_10k_chars_inr
        cred_val = credit_value_inr if credit_value_inr is not None else settings.credit_value_inr
        tf_usd = twilio_fallback_per_min_usd if twilio_fallback_per_min_usd is not None else settings.twilio_outbound_per_min_usd

        # Default STT seconds to duration_seconds if not provided
        stt_sec = stt_audio_seconds if stt_audio_seconds is not None else float(duration_seconds)
        
        # Default Twilio billable minutes to duration/60 (rounded up) if not provided
        if twilio_billable_minutes is None:
            tw_bill_min = float(math.ceil(duration_seconds / 60.0))
        else:
            tw_bill_min = float(twilio_billable_minutes)

        # 1. STT Cost (Deepgram)
        stt_cost_usd = (stt_sec / 3600.0) * dg_usd
        stt_cost_inr = stt_cost_usd * u_to_i

        # 2. LLM Cost
        llm_input_cost_usd = (llm_input_tokens / 1000000.0) * llm_in_usd
        llm_output_cost_usd = (llm_output_tokens / 1000000.0) * llm_out_usd
        llm_cost_usd = llm_input_cost_usd + llm_output_cost_usd
        llm_cost_inr = llm_cost_usd * u_to_i

        # 3. TTS Cost
        tts_cost_inr = (tts_characters / 10000.0) * sarvam_inr

        # 4. Telephony Cost (Twilio)
        if twilio_cost_source == "actual":
            telephony_cost_inr = twilio_cost_inr
        else:
            telephony_cost_usd = tw_bill_min * tf_usd
            telephony_cost_inr = telephony_cost_usd * u_to_i

        # Total Cost
        total_cost_inr = stt_cost_inr + llm_cost_inr + tts_cost_inr + telephony_cost_inr
        credits_used = total_cost_inr / cred_val if cred_val > 0 else total_cost_inr

        return {
            "duration_seconds": duration_seconds,
            "stt_audio_seconds": stt_sec,
            "stt_cost_inr": round(stt_cost_inr, 4),
            "llm_input_tokens": llm_input_tokens,
            "llm_output_tokens": llm_output_tokens,
            "llm_cost_inr": round(llm_cost_inr, 4),
            "tts_characters": tts_characters,
            "tts_cost_inr": round(tts_cost_inr, 4),
            "telephony_cost_inr": round(telephony_cost_inr, 4),
            "total_cost_inr": round(total_cost_inr, 4),
            "credits_used": round(credits_used, 4),
        }
    except Exception as e:
        logger.error(f"Error calculating costs: {e}", exc_info=True)
        return {
            "duration_seconds": duration_seconds,
            "stt_audio_seconds": duration_seconds,
            "stt_cost_inr": 0.0,
            "llm_input_tokens": llm_input_tokens,
            "llm_output_tokens": llm_output_tokens,
            "llm_cost_inr": 0.0,
            "tts_characters": tts_characters,
            "tts_cost_inr": 0.0,
            "telephony_cost_inr": 0.0,
            "total_cost_inr": 0.0,
            "credits_used": 0.0,
        }
