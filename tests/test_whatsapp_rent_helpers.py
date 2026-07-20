from src.services.whatsapp_rent_helpers import (
    rent_quick_buttons,
    rent_reset_reply,
)


def test_rent_quick_buttons_normal():
    buttons = rent_quick_buttons(handoff_active=False)
    assert len(buttons) == 3
    assert buttons[0]["id"] == "rent:balance"
    assert buttons[1]["id"] == "rent:pay"


def test_rent_quick_buttons_handoff():
    buttons = rent_quick_buttons(handoff_active=True)
    assert len(buttons) == 1
    assert buttons[0]["id"] == "agent:ai"


def test_rent_reset_reply_not_commerce():
    reply = rent_reset_reply("ATC Holdings")
    assert "cart" not in reply.lower()
    assert "ATC Holdings" in reply
