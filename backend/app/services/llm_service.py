import logging
from typing import AsyncGenerator, Dict, List, Optional

import openai

logger = logging.getLogger(__name__)


class LLMService:
    def __init__(self, openai_key: Optional[str], anthropic_key: Optional[str] = None):
        self.openai_client = openai.AsyncOpenAI(api_key=openai_key) if openai_key else None

    # ──────────────────────────────────────────
    # Non-streaming (used by phone webhook)
    # ──────────────────────────────────────────
    async def generate(
        self,
        system_prompt: str,
        messages: List[Dict[str, str]],
        model: str = "gpt-4o-mini",
        temperature: float = 0.7,
        max_tokens: int = 150,
    ) -> str:
        import time
        start_time = time.time()
        provider = "openai"
        try:
            # Force GPT-4o mini
            model_to_use = "gpt-4o-mini"
            if not self.openai_client:
                raise ValueError("OpenAI API key not configured")
            
            response = await self.openai_client.chat.completions.create(
                model=model_to_use,
                messages=[{"role": "system", "content": system_prompt}] + messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            res_content = response.choices[0].message.content or ""
            latency = int((time.time() - start_time) * 1000)
            from app.services.provider_health_service import log_provider_health_event
            log_provider_health_event(provider, "llm", "success", latency_ms=latency)
            return res_content
        except Exception as e:
            latency = int((time.time() - start_time) * 1000)
            from app.services.provider_health_service import log_provider_health_event
            status = "429_rate_limited" if "rate_limit" in str(e).lower() or "429" in str(e) else "failure"
            log_provider_health_event(provider, "llm", status, latency_ms=latency, error_code="API_ERROR", error_message=str(e))
            logger.error("LLM generate failed: %s", e)
            raise

    # ──────────────────────────────────────────
    # Streaming — yields raw token strings
    # ──────────────────────────────────────────
    async def generate_stream(
        self,
        system_prompt: str,
        messages: List[Dict[str, str]],
        model: str = "gpt-4o-mini",
        temperature: float = 0.7,
        max_tokens: int = 80,
    ) -> AsyncGenerator[str, None]:
        if not self.openai_client:
            raise ValueError("OpenAI API key not configured")

        # Force GPT-4o mini
        model_to_use = "gpt-4o-mini"

        import time
        start_time = time.time()
        first_token_logged = False
        try:
            stream = await self.openai_client.chat.completions.create(
                model=model_to_use,
                messages=[{"role": "system", "content": system_prompt}] + messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
            )
            async for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta:
                    if not first_token_logged:
                        latency = int((time.time() - start_time) * 1000)
                        from app.services.provider_health_service import log_provider_health_event
                        log_provider_health_event("openai", "llm", "success", latency_ms=latency)
                        first_token_logged = True
                    yield delta
        except Exception as e:
            latency = int((time.time() - start_time) * 1000)
            from app.services.provider_health_service import log_provider_health_event
            status = "429_rate_limited" if "rate_limit" in str(e).lower() or "429" in str(e) else "failure"
            log_provider_health_event("openai", "llm", status, latency_ms=latency, error_code="STREAM_ERROR", error_message=str(e))
            logger.error("LLM stream failed: %s", e)
            raise
