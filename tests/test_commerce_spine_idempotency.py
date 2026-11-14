"""Duplicate WhatsApp wamid is a single side effect after finalize."""

import pytest

from src.services.idempotency_service import ClaimResult, idempotency_service


@pytest.mark.asyncio
async def test_duplicate_wamid_is_noop_after_finalize(db_session, test_user):
    wamid = "wamid.DUPLICATE1"
    user_id = test_user.id
    side_effects = {"orders": 0}

    async def process_once():
        claim = await idempotency_service.claim_message(db_session, user_id, wamid)
        if claim in (ClaimResult.ALREADY_COMPLETED, ClaimResult.ALREADY_IN_PROGRESS):
            return
        side_effects["orders"] += 1
        await idempotency_service.mark_completed(
            db_session, user_id, wamid, processing_result="order_created"
        )

    await process_once()
    await process_once()

    assert side_effects["orders"] == 1


@pytest.mark.asyncio
async def test_completed_duplicate_skips_and_failed_wamid_reprocesses(db_session, test_user):
    user_id = test_user.id
    done = "wamid.DONE1"
    await idempotency_service.claim_message(db_session, user_id, done)
    await idempotency_service.mark_completed(db_session, user_id, done)
    assert await idempotency_service.duplicate_delivery_action(db_session, user_id, done) == "skip"

    failed = "wamid.FAIL1"
    await idempotency_service.claim_message(db_session, user_id, failed)
    await idempotency_service.mark_failed(db_session, user_id, failed)
    assert (
        await idempotency_service.duplicate_delivery_action(db_session, user_id, failed)
        == "reprocess"
    )


@pytest.mark.asyncio
async def test_workflow_exception_leaves_wamid_failed_not_completed(
    db_session, test_user, async_engine
):
    """A workflow error must not acknowledge the wamid, so a later delivery can run."""
    from unittest.mock import AsyncMock, patch

    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from src.models import ProcessedWebhookMessage, WhatsAppContact, WhatsAppMessage
    from src.routers.whatsapp_webhook import background_process_message
    from src.services.whatsapp_workflow_trigger import WhatsAppWorkflowTrigger

    contact = WhatsAppContact(
        user_id=test_user.id,
        phone_number="254700000001",
        name="Asha",
    )
    db_session.add(contact)
    await db_session.commit()
    await db_session.refresh(contact)
    message = WhatsAppMessage(
        user_id=test_user.id,
        contact_id=contact.id,
        direction="incoming",
        message_type="text",
        content="Hello",
        whatsapp_message_id="wamid.WORKFLOWFAIL1",
        status="received",
    )
    db_session.add(message)
    await db_session.commit()
    await db_session.refresh(message)
    await idempotency_service.claim_message(db_session, test_user.id, "wamid.WORKFLOWFAIL1")

    maker = async_sessionmaker(
        async_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )
    with patch(
        "src.routers.whatsapp_webhook.get_session_maker",
        return_value=maker,
    ), patch.object(
        WhatsAppWorkflowTrigger,
        "has_active_conversational_agent",
        new=AsyncMock(return_value=True),
    ), patch.object(
        WhatsAppWorkflowTrigger,
        "on_message_received",
        new=AsyncMock(side_effect=RuntimeError("agent down")),
    ), patch(
        "src.services.whatsapp_service.WhatsAppService.mark_message_read",
        new=AsyncMock(return_value=None),
    ):
        await background_process_message(
            test_user.id,
            contact.id,
            message.id,
            already_claimed=True,
        )

    row = (
        await db_session.execute(
            select(ProcessedWebhookMessage).where(
                ProcessedWebhookMessage.whatsapp_message_id == "wamid.WORKFLOWFAIL1"
            )
        )
    ).scalar_one()
    await db_session.refresh(row)
    assert row.processing_status == "failed"
    assert await idempotency_service.claim_message(
        db_session, test_user.id, "wamid.WORKFLOWFAIL1"
    ) == ClaimResult.STALE_RETRY
