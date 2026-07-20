"""Tests for WhatsApp inbox persistence and CCM merge."""

import uuid
from datetime import datetime, timezone

import pytest

from src.models import WhatsAppMessageDirection, WhatsAppMessageStatus
from src.services.whatsapp_inbox_service import (
    _is_internal_ccm_assistant_content,
    _outgoing_content_exists,
    build_ccm_session_key,
    merge_ccm_assistant_messages,
    merge_message_rows_for_api,
    normalize_whatsapp_phone,
)


def test_normalize_whatsapp_phone():
    assert normalize_whatsapp_phone("+254 712 345 678") == "254712345678"


def test_build_ccm_session_key():
    uid = "f90eb4b7-f155-49ce-b76f-518f8ca9b673"
    assert build_ccm_session_key(uid, "+254712345678") == (
        f"ccm:whatsapp:{uid}:254712345678"
    )


def test_internal_ccm_content_filtered():
    assert _is_internal_ccm_assistant_content("[SYSTEM: Order ORD-1 was created]")
    assert not _is_internal_ccm_assistant_content("Hello, your order is ready.")


def test_outgoing_content_exists_dedupes():
    class _Msg:
        def __init__(self, content):
            self.direction = WhatsAppMessageDirection.OUTGOING
            self.content = content

    persisted = [_Msg("  Hello  world ")]
    assert _outgoing_content_exists(persisted, "hello world")


def test_merge_message_rows_sorted():
    t1 = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 1, 1, 11, 0, tzinfo=timezone.utc)
    rows = merge_message_rows_for_api(
        [],
        [
            {
                "id": uuid.uuid4(),
                "direction": "outgoing",
                "message_type": "text",
                "content": "Agent reply",
                "media_url": None,
                "status": WhatsAppMessageStatus.SENT,
                "is_auto_reply": False,
                "is_agent": True,
                "is_internal_note": False,
                "created_at": t2,
                "delivered_at": None,
                "read_at": None,
            },
            {
                "id": uuid.uuid4(),
                "direction": "incoming",
                "message_type": "text",
                "content": "Hi",
                "media_url": None,
                "status": WhatsAppMessageStatus.DELIVERED,
                "is_auto_reply": False,
                "is_agent": False,
                "is_internal_note": False,
                "created_at": t1,
                "delivered_at": None,
                "read_at": None,
            },
        ],
    )
    assert rows[0]["content"] == "Hi"
    assert rows[1]["content"] == "Agent reply"


@pytest.mark.asyncio
async def test_merge_ccm_assistant_skips_duplicates_and_system():
    user_id = uuid.uuid4()
    contact_id = uuid.uuid4()

    class _Contact:
        id = contact_id
        phone_number = "254712345678"

    class _Persisted:
        direction = WhatsAppMessageDirection.OUTGOING
        content = "Already saved agent reply"

    class _Row:
        messages = [
            {"role": "user", "content": "Hi", "timestamp": "2026-01-01T10:00:00+00:00"},
            {
                "role": "assistant",
                "content": "[SYSTEM: hidden]",
                "timestamp": "2026-01-01T10:01:00+00:00",
            },
            {
                "role": "assistant",
                "content": "Already saved agent reply",
                "timestamp": "2026-01-01T10:02:00+00:00",
            },
            {
                "role": "assistant",
                "content": "New agent reply from CCM",
                "timestamp": "2026-01-01T10:03:00+00:00",
            },
        ]

    class _Result:
        def scalar_one_or_none(self):
            return _Row()

    class _Db:
        async def execute(self, _stmt):
            return _Result()

    synthetics = await merge_ccm_assistant_messages(
        _Db(),
        user_id=user_id,
        contact=_Contact(),
        persisted_messages=[_Persisted()],
    )
    assert len(synthetics) == 1
    assert synthetics[0]["content"] == "New agent reply from CCM"
    assert synthetics[0]["is_agent"] is True
