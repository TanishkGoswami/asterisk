import json
import logging
from typing import Dict, Any, Optional
from datetime import datetime
import pytz
from app.services.llm_service import LLMService
from app.core.config import settings

logger = logging.getLogger(__name__)

SCHEDULE_PARSER_PROMPT = """
You are an expert scheduling assistant. Your task is to convert natural language text into a structured JSON schedule object.
Current Time (UTC): {current_time_utc}
User Home Timezone: {user_timezone}

Output JSON format:
{{
  "task_type": "voice_call" | "follow_up" | "reminder",
  "title": "Action title (e.g., 'Call Amit')",
  "scheduled_time_utc": "ISO 8601 string in UTC if one-time or first run, else null",
  "timezone": "IANA timezone string (e.g., 'Asia/Kolkata')",
  "recurrence_rule": "RFC 5545 RRULE string (e.g., 'FREQ=WEEKLY;BYDAY=MO;BYHOUR=10') or null",
  "payload": {{ 
      "contact_name": "extracted name if any",
      "purpose": "extracted purpose if any",
      "original_text": "the input text"
  }},
  "clarification_needed": "If date or time is ambiguous or missing, ask a specific question. Else null."
}}

Rules:
1. One-time tasks: Provide 'scheduled_time_utc'. 'recurrence_rule' must be null.
2. Recurring tasks: Provide 'recurrence_rule'. Set 'scheduled_time_utc' to the first occurrence time in UTC.
3. Relative dates: "tomorrow at 11 AM" should be calculated based on the provided Current Time and User Timezone.
4. Default task_type is 'voice_call' unless specified otherwise.
5. Always output valid JSON only. No extra text.
"""

class ScheduleParserService:
    def __init__(self, llm: Optional[LLMService] = None):
        self.llm = llm or LLMService(
            openai_key=settings.openai_api_key,
        )

    async def parse(self, text: str, user_timezone: str = "UTC") -> Dict[str, Any]:
        """
        Parse natural language text into a structured schedule.
        """
        now_utc = datetime.now(pytz.utc).isoformat()
        
        system_prompt = SCHEDULE_PARSER_PROMPT.format(
            current_time_utc=now_utc,
            user_timezone=user_timezone
        )
        
        try:
            response_text = await self.llm.generate(
                system_prompt=system_prompt,
                messages=[{"role": "user", "content": text}],
                model="gpt-4o-mini",
                temperature=0.1, # Low temperature for consistent JSON
                max_tokens=500
            )
            
            # Clean response text in case LLM wraps it in markdown blocks
            cleaned_text = response_text.strip()
            if cleaned_text.startswith("```json"):
                cleaned_text = cleaned_text.split("```json")[1].split("```")[0]
            elif cleaned_text.startswith("```"):
                cleaned_text = cleaned_text.split("```")[1].split("```")[0]
            
            data = json.loads(cleaned_text.strip())
            
            # Post-processing: Ensure timezone is present
            if not data.get("timezone"):
                data["timezone"] = user_timezone
                
            return data
            
        except Exception as e:
            logger.error(f"Schedule parsing failed: {e}")
            return {
                "clarification_needed": "I'm sorry, I couldn't process that schedule. Could you please provide the date and time more clearly?",
                "error": str(e)
            }
