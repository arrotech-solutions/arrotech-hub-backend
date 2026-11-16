"""Duplicate WhatsApp wamid is a single side effect after finalize."""

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.services.idempotency_service import ClaimResult, idempotency_service


@pytest.mark.asyncio
async def test_duplicate_meta_wamid_skips_order_workflow():
    from src.routers.whatsapp_webhook import background_process_message
    from src.services.whatsapp_workflow_trigger import WhatsAppWorkflowTrigger

    contact_id = uuid.uuid4()
    message_id = uuid.uuid4()
    user_id = uuid.uuid4()
    contact = MagicMock(phone_number="254700000001")
    message = MagicMock(whatsapp_message_id="wamid.ALREADY_COMPLETED")
    query_results = [contact, message]

    class FakeDb:
        def __init__(self):
            self.execute = AsyncMock(
                side_effect=[
                    MagicMock(scalar_one_or_none=MagicMock(return_value=result))
                    for result in query_results
                ]
            )

    db = FakeDb()

    class FakeSessionContext:
        async def __aenter__(self):
            return db

        async def __aexit__(self, *_args):
            return False

    class FakeSessionMaker:
        def __call__(self):
            return FakeSessionContext()

    with patch(
        "src.routers.whatsapp_webhook.get_session_maker",
        return_value=FakeSessionMaker(),
    ), patch(
        "src.database.set_tenant_context",
        new_callable=AsyncMock,
    ), patch.object(
        idempotency_service,
        "claim_message",
        new_callable=AsyncMock,
        return_value=ClaimResult.ALREADY_COMPLETED,
    ) as claim, patch.object(
        WhatsAppWorkflowTrigger,
        "on_message_received",
        new_callable=AsyncMock,
    ) as workflow:
        await background_process_message(user_id, contact_id, message_id)

    claim.assert_awaited_once_with(db, user_id, "wamid.ALREADY_COMPLETED")
    workflow.assert_not_awaited()
    assert db.execute.await_count == 2


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


@pytest.mark.asyncio
async def test_order_followup_fallback_claim_is_atomic_and_scoped(
    db_session, test_user
):
    from src.models import ProcessedWebhookMessage

    user_id = test_user.id
    first_id = "wamid.FALLBACK-CLAIM-1"
    other_id = "wamid.FALLBACK-CLAIM-2"
    await idempotency_service.claim_message(db_session, user_id, first_id)
    await idempotency_service.claim_message(db_session, user_id, other_id)

    assert await idempotency_service.claim_order_followup_fallback(
        db_session, user_id, first_id
    ) is True
    assert await idempotency_service.claim_order_followup_fallback(
        db_session, user_id, first_id
    ) is False
    assert await idempotency_service.claim_order_followup_fallback(
        db_session, user_id, other_id
    ) is True

    rows = (
        await db_session.execute(
            select(ProcessedWebhookMessage).where(
                ProcessedWebhookMessage.user_id == user_id,
                ProcessedWebhookMessage.whatsapp_message_id.in_(
                    [first_id, other_id]
                ),
            )
        )
    ).scalars().all()
    assert {row.processing_result for row in rows} == {
        idempotency_service.ORDER_FOLLOWUP_FALLBACK_MARKER
    }


@pytest.mark.asyncio
async def test_order_followup_fallback_claim_fails_closed_for_missing_or_error(
    db_session, test_user
):
    assert await idempotency_service.claim_order_followup_fallback(
        db_session, test_user.id, "wamid.MISSING-FALLBACK-ROW"
    ) is False

    with patch.object(
        db_session,
        "execute",
        new=AsyncMock(side_effect=RuntimeError("database unavailable")),
    ):
        assert await idempotency_service.claim_order_followup_fallback(
            db_session, test_user.id, "wamid.FALLBACK-DB-ERROR"
        ) is False


@pytest.mark.asyncio
async def test_mark_completed_preserves_order_followup_fallback_marker(
    db_session, test_user
):
    from src.models import ProcessedWebhookMessage

    user_id = test_user.id
    wamid = "wamid.FALLBACK-MARK-COMPLETED"
    await idempotency_service.claim_message(db_session, user_id, wamid)
    assert await idempotency_service.claim_order_followup_fallback(
        db_session, user_id, wamid
    ) is True

    await idempotency_service.mark_completed(db_session, user_id, wamid)
    row = (
        await db_session.execute(
            select(ProcessedWebhookMessage).where(
                ProcessedWebhookMessage.user_id == user_id,
                ProcessedWebhookMessage.whatsapp_message_id == wamid,
            )
        )
    ).scalar_one()

    assert row.processing_status == "completed"
    assert row.processing_result == idempotency_service.ORDER_FOLLOWUP_FALLBACK_MARKER


@pytest.mark.asyncio
async def test_concurrent_fallback_for_same_meta_id_sends_at_most_once(
    db_session, test_user, async_engine
):
    from src.services.order_tracking_service import order_tracking_service

    user_id = test_user.id
    wamid = "wamid.FALLBACK-CONCURRENT"
    await idempotency_service.claim_message(db_session, user_id, wamid)
    session_factory = async_sessionmaker(
        async_engine, class_=AsyncSession, expire_on_commit=False
    )
    sends = []

    class FakeWhatsApp:
        async def send_message(self, phone, message, *, config):
            sends.append((phone, message))
            return {"success": True}

    registry = {}

    def save_registry(_owner_id, _order_id, value):
        registry.update(value)

    with patch.object(
        order_tracking_service,
        "_get_whatsapp_config",
        new=AsyncMock(return_value={"access_token": "token", "phone_number_id": "id"}),
    ), patch.object(
        order_tracking_service,
        "get_registered_order",
        side_effect=lambda *_args: dict(registry) if registry else None,
    ), patch.object(
        order_tracking_service, "_save_registry", side_effect=save_registry
    ), patch(
        "src.services.whatsapp_service.WhatsAppService", return_value=FakeWhatsApp()
    ):
        async def send_with_new_session():
            async with session_factory() as db:
                return await order_tracking_service.send_order_placement_fallback(
                    user=test_user,
                    db=db,
                    customer_phone="254700000001",
                    order_id="ORD-FALLBACK-CONCURRENT",
                    business_name="Shop",
                    meta_message_id=wamid,
                )

        results = await asyncio.gather(
            send_with_new_session(), send_with_new_session()
        )

    assert sum(bool(result.get("success")) and not result.get("skipped") for result in results) <= 1
    assert len(sends) <= 1
