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
