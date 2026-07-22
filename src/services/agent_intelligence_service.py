"""
Agent intelligence for WhatsApp/Telegram ordering agents.

- Multilingual: detect customer language and persist preference in CCM metadata
- Smart escalation: frustration/complexity signals and seamless human handoff
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ISO 639-1 codes → display name for prompts and customer messages
LANGUAGE_PROFILES: Dict[str, Dict[str, str]] = {
    "en": {"name": "English", "native": "English"},
    "sw": {"name": "Swahili", "native": "Kiswahili"},
    "sheng": {"name": "Sheng", "native": "Sheng"},  # Kenyan Swahili-English slang
    "fr": {"name": "French", "native": "Français"},
    "ar": {"name": "Arabic", "native": "العربية"},
    "es": {"name": "Spanish", "native": "Español"},
    "pt": {"name": "Portuguese", "native": "Português"},
    "hi": {"name": "Hindi", "native": "हिन्दी"},
    "so": {"name": "Somali", "native": "Soomaali"},
    "am": {"name": "Amharic", "native": "አማርኛ"},
}

DEFAULT_LANGUAGE = "en"

# Phrases that request a human (multiple languages)
HUMAN_REQUEST_PATTERNS = [
    r"\b(speak|talk)\s+(to|with)\s+(a\s+)?(human|person|agent|manager|someone)\b",
    r"\b(real|live)\s+(person|agent|human)\b",
    r"\b(customer\s+service|human\s+support)\b",
    r"\b(need|want)\s+(a\s+)?human\b",
    r"\boperator\b",
    r"\b(nataka|nahitaji)\s+(mtu|mwakilishi|meneja)\b",  # Swahili
    r"\b(zungumza|ongea|kuongea)\s+na\s+(mtu|mwakilishi)\b",
    r"\b(nataka|nahitaji)\s+\w+\s+na\s+(mtu|mwakilishi|meneja)\b",
    r"\b(parler\s+à\s+(une?\s+)?(personne|humain))\b",  # French
    r"\bagent\s+humain\b",
    r"\bhablar\s+con\s+(una?\s+)?persona\b",  # Spanish
]

HUMAN_REQUEST_RE = re.compile("|".join(f"(?:{p})" for p in HUMAN_REQUEST_PATTERNS), re.IGNORECASE)

# Frustration / negative sentiment markers
FRUSTRATION_MARKERS_EN = [
    "ridiculous", "unacceptable", "terrible", "worst", "angry", "furious",
    "useless", "waste of time", "complaint", "refund now", "sue", "lawyer",
    "never again", "disgusting", "scam", "fraud", "pathetic",
]
FRUSTRATION_MARKERS_SW = [
    "mbaya sana", "sijapenda", "malipo", "rudisha pesa", "shida kubwa",
    "haitoshi", "pole sana", "nakataa", "hakuna haja", "udanganyifu",
]
FRUSTRATION_MARKERS_FR = [
    "inacceptable", "horrible", "remboursement", "plainte", "nul",
]

COMPLEXITY_MARKERS = [
    r"\b(custom|bulk|wholesale|corporate|b2b)\s+order\b",
    r"\b(\d{2,})\s*(units|items|pieces|plates)\b",
    r"\b(negotiat|discount for|special arrangement)\b",
    r"\b(allerg(y|ies)|dietary|halal|kosher|vegan)\b.*\b(several|multiple|many)\b",
]

COMPLEXITY_RE = re.compile("|".join(f"(?:{p})" for p in COMPLEXITY_MARKERS), re.IGNORECASE)

# Swahili function-word hints for detection
SWAHILI_HINTS = {
    "habari", "asante", "karibu", "tafadhali", "nataka", "nahitaji", "bei",
    "leo", "kesho", "nime", "nina", "yako", "yangu", "sawa", "ndiyo", "hapana",
    "chakula", "menu", "mzigo", "delivery", "malipo",
}
FRENCH_HINTS = {
    "bonjour", "merci", "s'il", "vous", "je", "veux", "commander", "livraison",
    "prix", "aujourd", "demain", "oui", "non", "s'il vous plaît",
}
SPANISH_HINTS = {
    "hola", "gracias", "por favor", "quiero", "pedido", "entrega", "precio",
    "hoy", "mañana", "sí", "no",
}
# Sheng (Kenyan slang) markers — Swahili/English code-mix
SHENG_HINTS = {
    "niaje", "sasa", "mambo", "poa", "fiti", "buda", "manze", "maze", "doo",
    "chums", "rongo", "noma", "form", "vipi", "msee", "wadau", "mtaa", "kuja",
    "fanya", "nare", "githeri", "ngata", "mob", "sare", "kakitu", "uko", "niko",
    "sema", "tu", "bro", "uki", "umeona",
}

ARABIC_SCRIPT_RE = re.compile(r"[\u0600-\u06FF\u0750-\u077F]")

HANDOFF_CUSTOMER_MESSAGES: Dict[str, str] = {
    "en": (
        "I've connected you with our team. 🙋 A human agent will reply here shortly. "
        "You can keep sending messages — they'll see everything."
    ),
    "sw": (
        "Nimekuunganisha na timu yetu. 🙋 Mtu atakujibu hapa hivi karibuni. "
        "Unaweza kuendelea kutuma ujumbe — wataona yote."
    ),
    "fr": (
        "Je vous ai mis en relation avec notre équipe. 🙋 Un agent vous répondra ici sous peu. "
        "Vous pouvez continuer à envoyer des messages."
    ),
    "ar": (
        "تم ربطك بفريقنا. 🙋 سيرد عليك أحد الوكلاء قريبًا. يمكنك متابعة إرسال الرسائل."
    ),
    "es": (
        "Te he conectado con nuestro equipo. 🙋 Un agente humano responderá pronto. "
        "Puedes seguir enviando mensajes."
    ),
}

HANDOFF_WAITING_MESSAGES: Dict[str, str] = {
    "en": "Thanks for your message — our team is reviewing your chat and will reply soon. 🙏",
    "sw": "Asante kwa ujumbe wako — timu yetu inaangalia na itakujibu hivi karibuni. 🙏",
    "fr": "Merci pour votre message — notre équipe examine votre conversation et vous répondra bientôt. 🙏",
    "ar": "شكرًا على رسالتك — فريقنا يراجع المحادثة وسيرد قريبًا. 🙏",
    "es": "Gracias por tu mensaje — nuestro equipo está revisando el chat y responderá pronto. 🙏",
}

RELEASE_BOT_KEYWORDS = {"resume bot", "/bot", "back to bot", "anza bot", "endelea na bot"}

RELEASE_BOT_MESSAGES: Dict[str, str] = {
    "en": "You're back with our AI assistant. 🤖 How can I help you today?",
    "sw": "Umerudi kwa msaidizi wetu wa AI. 🤖 Nawezaje kukusaidia leo?",
    "fr": "Vous êtes de nouveau avec notre assistant IA. 🤖 Comment puis-je vous aider ?",
    "ar": "عدت إلى مساعدنا الذكي. 🤖 كيف يمكنني مساعدتك اليوم؟",
    "es": "Has vuelto con nuestro asistente de IA. 🤖 ¿En qué puedo ayudarte hoy?",
}


class AgentIntelligenceService:
    """Language detection, sentiment/frustration scoring, and escalation helpers."""

    def detect_language(
        self,
        text: str,
        supported: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Detect language from message text using lightweight heuristics.
        Returns language_code, language_name, confidence (0-1).
        """
        supported = supported or list(LANGUAGE_PROFILES.keys())
        supported_set = {s.lower()[:2] for s in supported}

        if not (text or "").strip():
            code = DEFAULT_LANGUAGE if DEFAULT_LANGUAGE in supported_set else next(iter(supported_set), "en")
            return self._lang_result(code, 0.3)

        if ARABIC_SCRIPT_RE.search(text):
            code = "ar" if "ar" in supported_set else DEFAULT_LANGUAGE
            return self._lang_result(code, 0.92)

        lower = text.lower()
        words = set(re.findall(r"[a-zA-ZàâäéèêëïîôùûüçÀ-ÿ']+", lower))

        scores: Dict[str, float] = {"en": 0.1}
        sw_hits = len(words & SWAHILI_HINTS)
        fr_hits = len(words & FRENCH_HINTS)
        es_hits = len(words & SPANISH_HINTS)
        sheng_hits = len(words & SHENG_HINTS)

        if sw_hits:
            scores["sw"] = 0.4 + min(sw_hits * 0.15, 0.5)
        if fr_hits:
            scores["fr"] = 0.35 + min(fr_hits * 0.12, 0.45)
        if es_hits:
            scores["es"] = 0.35 + min(es_hits * 0.12, 0.45)
        if sheng_hits:
            # Sheng outscores plain Swahili when its distinctive slang appears.
            scores["sheng"] = 0.45 + min(sheng_hits * 0.18, 0.5)
            # Sheng is acceptable when the business supports Swahili or Sheng.
            if "sheng" not in supported_set and "sw" in supported_set:
                supported_set = supported_set | {"sheng"}

        # Default English boost when Latin script and no strong other signal
        if max(scores.values()) <= 0.2:
            scores["en"] = 0.75

        # Pick best among supported
        best_code = DEFAULT_LANGUAGE
        best_score = 0.0
        for code, score in scores.items():
            if code in supported_set and score > best_score:
                best_code = code
                best_score = score

        if best_code not in supported_set:
            best_code = DEFAULT_LANGUAGE if DEFAULT_LANGUAGE in supported_set else list(supported_set)[0]
            best_score = 0.5

        return self._lang_result(best_code, min(best_score, 0.95))

    def _lang_result(self, code: str, confidence: float) -> Dict[str, Any]:
        profile = LANGUAGE_PROFILES.get(code, LANGUAGE_PROFILES[DEFAULT_LANGUAGE])
        return {
            "language_code": code,
            "language_name": profile["name"],
            "language_native": profile.get("native", profile["name"]),
            "confidence": round(confidence, 2),
        }

    def build_language_instruction(self, language_code: str) -> str:
        """System-prompt block forcing replies in the customer's language."""
        profile = LANGUAGE_PROFILES.get(language_code, LANGUAGE_PROFILES[DEFAULT_LANGUAGE])
        name = profile["name"]
        native = profile.get("native", name)
        mirror_rule = (
            "- ALWAYS mirror the customer's language on every reply. If they write in one "
            "language now and switch to another later, switch with them.\n"
            "- Only change language when the customer's own message changes language, or "
            "when they explicitly ask you to use a specific language.\n"
        )
        if language_code == "sheng":
            return (
                "\n## Language (CRITICAL)\n"
                "- The customer is speaking **Sheng** (Kenyan Swahili-English street slang).\n"
                "- Reply in natural, friendly Sheng — mix Swahili and English the way young "
                "Kenyans chat (e.g. 'Niaje! Iko poa, nimekuget. Total ni KES 500, uko fiti?'). "
                "Keep it respectful and clear.\n"
                + mirror_rule
            )
        if language_code == "en":
            return (
                "\n## Language (CRITICAL)\n"
                "- The customer's preferred language is **English**.\n"
                "- Reply entirely in English.\n"
                + mirror_rule
            )
        return (
            f"\n## Language (CRITICAL)\n"
            f"- The customer's preferred language is **{name}** ({native}).\n"
            f"- Reply entirely in {name}. Use natural, conversational {name} — not word-for-word translation.\n"
            f"- Keep product names and brand terms as appropriate for the locale.\n"
            f"- If you are unsure of a term, prefer simple {name} the customer will understand.\n"
            + mirror_rule
        )

    def analyze_customer_sentiment(self, text: str) -> Dict[str, Any]:
        """Score sentiment and frustration from the latest customer message."""
        if not text:
            return {"sentiment": "neutral", "score": 0.5, "frustration_score": 0.0}

        lower = text.lower()
        frustration = 0.0

        for marker in FRUSTRATION_MARKERS_EN + FRUSTRATION_MARKERS_SW + FRUSTRATION_MARKERS_FR:
            if marker in lower:
                frustration += 0.25

        if "!" in text:
            frustration += min(text.count("!") * 0.08, 0.24)
        if text.isupper() and len(text) > 12:
            frustration += 0.2

        caps_words = sum(1 for w in text.split() if len(w) > 2 and w.isupper())
        if caps_words >= 2:
            frustration += 0.15

        frustration = min(frustration, 1.0)

        if frustration >= 0.5:
            sentiment = "negative"
            score = max(0.1, 0.5 - frustration * 0.4)
        elif frustration >= 0.25:
            sentiment = "mixed"
            score = 0.4
        else:
            sentiment = "positive" if any(w in lower for w in ("thank", "asante", "merci", "great", "perfect")) else "neutral"
            score = 0.7 if sentiment == "positive" else 0.55

        return {
            "sentiment": sentiment,
            "score": round(score, 2),
            "frustration_score": round(frustration, 2),
        }

    def wants_human_agent(self, text: str) -> bool:
        if not text:
            return False
        return bool(HUMAN_REQUEST_RE.search(text))

    def is_complex_query(self, text: str) -> bool:
        if not text:
            return False
        return bool(COMPLEXITY_RE.search(text))

    def should_auto_escalate(
        self,
        message: str,
        session_metadata: Optional[Dict[str, Any]],
        *,
        auto_escalation_enabled: bool = True,
        frustration_threshold: float = 0.65,
        consecutive_negative_limit: int = 3,
    ) -> Tuple[bool, str]:
        """
        Decide if the conversation should auto-escalate before the LLM runs.
        Returns (should_escalate, reason_code).
        """
        if not auto_escalation_enabled:
            return False, ""

        meta = session_metadata or {}
        if meta.get("human_handoff"):
            return False, ""

        if self.wants_human_agent(message):
            return True, "customer_requested_human"

        if self.is_complex_query(message):
            return True, "complex_query"

        sentiment = self.analyze_customer_sentiment(message)
        if sentiment["frustration_score"] >= frustration_threshold:
            return True, "high_frustration"

        # Track consecutive negative turns in metadata
        streak = int(meta.get("negative_sentiment_streak", 0))
        if sentiment["sentiment"] in ("negative", "mixed") and sentiment["frustration_score"] >= 0.35:
            streak += 1
        else:
            streak = 0

        if streak >= consecutive_negative_limit:
            return True, "repeated_frustration"

        return False, ""

    def update_sentiment_streak(
        self,
        session_metadata: Dict[str, Any],
        message: str,
    ) -> int:
        """Return updated negative streak count (caller persists to CCM)."""
        sentiment = self.analyze_customer_sentiment(message)
        streak = int(session_metadata.get("negative_sentiment_streak", 0))
        if sentiment["sentiment"] in ("negative", "mixed") and sentiment["frustration_score"] >= 0.35:
            return streak + 1
        return 0

    def format_escalation_notification(
        self,
        *,
        business_name: str,
        customer_name: str,
        customer_phone: str,
        reason: str,
        last_message: str,
        language_name: str = "English",
    ) -> str:
        reason_labels = {
            "customer_requested_human": "Customer asked for a human agent",
            "high_frustration": "Customer appears frustrated",
            "repeated_frustration": "Repeated negative messages",
            "complex_query": "Complex request (needs human judgment)",
            "agent_escalation": "AI escalated the conversation",
            "business_replied": "You took over the chat",
        }
        reason_text = reason_labels.get(reason, reason.replace("_", " ").title())

        preview = (last_message or "")[:200]
        if len(last_message or "") > 200:
            preview += "…"

        name = customer_name or "Customer"
        phone = customer_phone or "Unknown"

        return (
            f"🚨 *Human handoff — {business_name}*\n\n"
            f"👤 {name} ({phone})\n"
            f"🌐 Language: {language_name}\n"
            f"📋 Reason: {reason_text}\n\n"
            f"💬 Last message:\n_{preview}_\n\n"
            f"Reply from your WhatsApp dashboard — the AI is paused for this customer "
            f"until you release the chat (send `/bot` from dashboard or release in Hub)."
        )

    def get_handoff_customer_message(self, language_code: str) -> str:
        return HANDOFF_CUSTOMER_MESSAGES.get(
            language_code,
            HANDOFF_CUSTOMER_MESSAGES[DEFAULT_LANGUAGE],
        )

    def get_handoff_waiting_message(self, language_code: str) -> str:
        return HANDOFF_WAITING_MESSAGES.get(
            language_code,
            HANDOFF_WAITING_MESSAGES[DEFAULT_LANGUAGE],
        )

    def is_release_bot_command(self, message: str) -> bool:
        if not message:
            return False
        normalized = message.strip().lower()
        return normalized in RELEASE_BOT_KEYWORDS

    def get_release_bot_message(self, language_code: str) -> str:
        return RELEASE_BOT_MESSAGES.get(
            language_code,
            RELEASE_BOT_MESSAGES[DEFAULT_LANGUAGE],
        )

    def handoff_expired(self, session_metadata: Dict[str, Any], ttl_seconds: int) -> bool:
        """True if human handoff TTL elapsed (auto-resume bot)."""
        if not session_metadata.get("human_handoff"):
            return False
        escalated_at = session_metadata.get("escalated_at")
        if not escalated_at:
            return False
        try:
            return (time.time() - float(escalated_at)) > ttl_seconds
        except (TypeError, ValueError):
            return False


agent_intelligence = AgentIntelligenceService()
