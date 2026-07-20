"""WhatsApp quick-reply helpers for rent collection agents."""
from typing import Dict, List


RENT_BUTTON_BALANCE = "rent:balance"
RENT_BUTTON_PAY = "rent:pay"
RENT_BUTTON_TALK = "agent:human"
RENT_BUTTON_BACK_TO_AI = "agent:ai"


def rent_reset_reply(business_name: str, language_code: str = "en") -> str:
    if language_code == "sw":
        return (
            f"🔄 Mwanzo mpya! Historia ya mazungumzo imefutwa.\n\n"
            f"Karibu tena *{business_name}* — naweza kukusaidia na kodi, salio, na malipo."
        )
    return (
        f"🔄 Fresh start! Your chat history is cleared.\n\n"
        f"Welcome back to *{business_name}* — I can help with rent, balance, and payments."
    )


def rent_release_bot_message(language_code: str, business_name: str) -> str:
    if language_code == "sw":
        return (
            f"✅ Msaidizi wa AI umerudishwa. Unaweza kuendelea kuzungumza na boti ya *{business_name}*."
        )
    return (
        f"✅ AI assistant is back on. You can continue chatting with *{business_name}*."
    )


def rent_quick_button_body(handoff_active: bool) -> str:
    if handoff_active:
        return "Tap below when you'd like to chat with the AI assistant again."
    return "Quick options — tap below or type your question."


def rent_quick_buttons(handoff_active: bool) -> List[Dict[str, str]]:
    """WhatsApp reply buttons for rent collection (max 3)."""
    if handoff_active:
        return [{"id": RENT_BUTTON_BACK_TO_AI, "title": "Chat with AI"}]
    return [
        {"id": RENT_BUTTON_BALANCE, "title": "My balance"},
        {"id": RENT_BUTTON_PAY, "title": "Pay rent"},
        {"id": RENT_BUTTON_TALK, "title": "Talk to us"},
    ]
