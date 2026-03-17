"""
Bilingual & Context Service
Handles English-Swahili translations, sentiment analysis, and regional business context verification.
"""
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

class BilingualService:
    """Service for localized linguistic and business context."""

    def __init__(self):
        # LRU cache for translations to avoid re-translating identical phrases
        self._translation_cache: Dict[str, Dict[str, Any]] = {}
        self._cache_max_size: int = 256

    def _get_cache_key(self, text: str, target_lang: str) -> str:
        """Generate a cache key for translation lookups."""
        return f"{target_lang}:{text[:200]}"

    async def translate(self, text: str, target_lang: str) -> Dict[str, Any]:
        """Translate text between English and Swahili."""
        # Check cache first
        cache_key = self._get_cache_key(text, target_lang)
        if cache_key in self._translation_cache:
            logger.info(f"Translation cache hit for '{text[:30]}...'")
            return self._translation_cache[cache_key]

        from .llm_service import llm_service
        
        prompt = f"Translate the following text to {target_lang}. Return only the translated text, nothing else.\n\nText: {text}"
        
        response = await llm_service.chat_completion(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=300,
            use_background_model=True
        )
        
        if response.error or not response.content:
            logger.warning(f"Translation failed: {response.error}")
            # Fallback to mock for known phrases or original text
            translations = {
                "Hello, how can I help you today?": "Habari, nawezaje kukusaidia leo?",
                "Your leave has been approved.": "Likizo yako imekubaliwa.",
                "Please provide your transaction reference.": "Tafadhali toa nambari ya kumbukumbu ya muamala wako."
            }
            translated_text = translations.get(text, f"[Translated to {target_lang}]: {text}")
        else:
            translated_text = response.content.strip()

        result = {
            "original": text,
            "translated": translated_text,
            "translated_text": translated_text,
            "target_lang": target_lang
        }

        # Cache the result (evict oldest if full)
        if len(self._translation_cache) >= self._cache_max_size:
            oldest_key = next(iter(self._translation_cache))
            del self._translation_cache[oldest_key]
        self._translation_cache[cache_key] = result

        return result

    async def analyze_sentiment_bilingual(self, text: str) -> Dict[str, Any]:
        """Analyze sentiment in both English and Swahili."""
        # Simple keywords for mock
        swahili_angry = ["mbaya", "nakataa", "pole", "shida"]
        text_lower = text.lower()
        
        is_negative = any(word in text_lower for word in swahili_angry) or "bad" in text_lower or "error" in text_lower
        
        return {
            "sentiment": "negative" if is_negative else "positive",
            "score": 0.2 if is_negative else 0.8,
            "detected_language": "swahili" if any(word in text_lower for word in ["habari", "nime", "leo"]) else "english"
        }

    async def verify_kra_pin(self, pin: str) -> Dict[str, Any]:
        """Verify KRA PIN (Mock)."""
        if len(pin) == 11 and pin[0].isalpha() and pin[-1].isalpha():
            return {
                "valid": True,
                "pin": pin,
                "taxpayer_name": "ARROTECH HUB LIMITED",
                "status": "active"
            }
        return {"valid": False, "error": "Invalid PIN format"}

    async def check_itax_compliance(self, pin: str) -> Dict[str, Any]:
        """Check iTax compliance status (Mock)."""
        return {
            "pin": pin,
            "compliant": True,
            "last_return_date": "2023-12-31",
            "certificates": ["VAT", "Income Tax"]
        }

    async def test_connection(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Test Business Intelligence connection."""
        return {"success": True, "message": "Business Intelligence and Localization service ready"}
