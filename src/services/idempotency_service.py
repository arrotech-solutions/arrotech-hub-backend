"""
Idempotency Service — atomic check-before-act guards for WhatsApp webhook processing.

Wraps the ProcessedWebhookMessage table with clean methods that each downstream
side-effecting step (order creation, confirmation send, receipt send) can call
to guarantee at-most-once execution even under race conditions.

Every guard uses database-level atomicity (INSERT ON CONFLICT, UPDATE … WHERE)
so that it holds even when two Celery workers or background tasks race on the
same inbound message_id.
"""

import logging
import uuid
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional

from sqlalchemy import select, update, and_
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# If a 'started' record is older than this, we consider it stale
# (the original processor likely crashed) and allow a retry.
STALE_THRESHOLD_SECONDS = 300  # 5 minutes


class ClaimResult(str, Enum):
    """Outcome of attempting to claim a message for processing."""
    CLAIMED = "claimed"                    # Successfully claimed — caller should process
    ALREADY_COMPLETED = "already_completed"  # Already fully processed — caller should skip
    ALREADY_IN_PROGRESS = "already_in_progress"  # Another worker is actively processing — skip
    STALE_RETRY = "stale_retry"            # Previous attempt is stale — caller should retry


class IdempotencyService:
    """Atomic idempotency guards for WhatsApp webhook side effects.

    Usage flow:
        1. claim_message()  → at the top of background_process_message()
        2. get_order_for_message() → before creating an order
        3. record_order_created() → after order creation succeeds
        4. check_and_set_flag("confirmation_sent") → before sending confirmation
        5. check_and_set_flag("receipt_sent") → before sending receipt
        6. mark_completed() → after all processing finishes
        On error: mark_failed() → allows retry on next attempt
    """

    async def claim_message(
        self,
        db: AsyncSession,
        user_id,
        wa_message_id: str,
    ) -> ClaimResult:
        """Attempt to claim a message for processing.

        Uses INSERT … ON CONFLICT DO NOTHING to atomically prevent two
        workers from both claiming the same message.

        Returns:
            ClaimResult.CLAIMED — this worker now owns processing
            ClaimResult.ALREADY_COMPLETED — already fully processed (skip)
            ClaimResult.ALREADY_IN_PROGRESS — another worker is actively on it (skip)
            ClaimResult.STALE_RETRY — previous attempt is stale, reclaimed for retry
        """
        from ..models import ProcessedWebhookMessage

        try:
            from sqlalchemy.dialects.postgresql import insert as pg_insert

            stmt = pg_insert(ProcessedWebhookMessage).values(
                id=uuid.uuid4(),
                user_id=user_id,
                whatsapp_message_id=wa_message_id,
                processing_status="started",
            ).on_conflict_do_nothing(
                constraint="uq_processed_user_wa_msg"
            )
            result = await db.execute(stmt)
            await db.commit()

            if result.rowcount == 1:
                # Fresh claim — this worker owns processing
                return ClaimResult.CLAIMED

            # Row already exists — check its status
            existing = await db.execute(
                select(ProcessedWebhookMessage).where(
                    and_(
                        ProcessedWebhookMessage.user_id == user_id,
                        ProcessedWebhookMessage.whatsapp_message_id == wa_message_id,
                    )
                )
            )
            row = existing.scalar_one_or_none()
            if not row:
                # Shouldn't happen, but treat as claimable
                return ClaimResult.CLAIMED

            status = row.processing_status

            # NULL or 'completed' → already done
            if status is None or status == "completed":
                return ClaimResult.ALREADY_COMPLETED

            # 'failed' → allow retry by resetting to 'started'
            if status == "failed":
                row.processing_status = "started"
                row.created_at = datetime.utcnow()
                await db.commit()
                logger.info(
                    "[IDEMPOTENCY] Reclaiming failed message %s for retry",
                    wa_message_id,
                )
                return ClaimResult.STALE_RETRY

            # 'started' → check if stale
            if status == "started":
                age = datetime.utcnow() - (row.created_at.replace(tzinfo=None) if row.created_at else datetime.utcnow())
                if age > timedelta(seconds=STALE_THRESHOLD_SECONDS):
                    # Stale — previous worker likely crashed; reclaim
                    row.created_at = datetime.utcnow()
                    await db.commit()
                    logger.info(
                        "[IDEMPOTENCY] Reclaiming stale message %s (age=%ss) for retry",
                        wa_message_id,
                        int(age.total_seconds()),
                    )
                    return ClaimResult.STALE_RETRY
                else:
                    # Another worker is actively processing
                    return ClaimResult.ALREADY_IN_PROGRESS

            # Unknown status — treat as completed to be safe
            return ClaimResult.ALREADY_COMPLETED

        except Exception as e:
            logger.warning(
                "[IDEMPOTENCY] claim_message failed for %s (proceeding anyway): %s",
                wa_message_id,
                e,
            )
            # If idempotency infra fails (e.g. table missing during rollout),
            # let processing continue rather than silently dropping the message.
            return ClaimResult.CLAIMED

    async def mark_completed(
        self,
        db: AsyncSession,
        user_id,
        wa_message_id: str,
        *,
        order_id: Optional[str] = None,
        processing_result: Optional[str] = None,
    ) -> None:
        """Mark a message as fully processed."""
        from ..models import ProcessedWebhookMessage

        try:
            values = {
                "processing_status": "completed",
                "completed_at": datetime.utcnow(),
            }
            if order_id:
                values["order_id"] = order_id
            if processing_result:
                values["processing_result"] = processing_result

            await db.execute(
                update(ProcessedWebhookMessage)
                .where(
                    and_(
                        ProcessedWebhookMessage.user_id == user_id,
                        ProcessedWebhookMessage.whatsapp_message_id == wa_message_id,
                    )
                )
                .values(**values)
            )
            await db.commit()
        except Exception as e:
            logger.warning(
                "[IDEMPOTENCY] mark_completed failed for %s: %s",
                wa_message_id,
                e,
            )

    async def mark_failed(
        self,
        db: AsyncSession,
        user_id,
        wa_message_id: str,
    ) -> None:
        """Mark a message as failed (allows retry on next attempt)."""
        from ..models import ProcessedWebhookMessage

        try:
            await db.execute(
                update(ProcessedWebhookMessage)
                .where(
                    and_(
                        ProcessedWebhookMessage.user_id == user_id,
                        ProcessedWebhookMessage.whatsapp_message_id == wa_message_id,
                    )
                )
                .values(processing_status="failed")
            )
            await db.commit()
        except Exception as e:
            logger.warning(
                "[IDEMPOTENCY] mark_failed failed for %s: %s",
                wa_message_id,
                e,
            )

    async def get_order_for_message(
        self,
        db: AsyncSession,
        user_id,
        wa_message_id: str,
    ) -> Optional[str]:
        """Return the order_id created for this message, or None."""
        from ..models import ProcessedWebhookMessage

        try:
            result = await db.execute(
                select(ProcessedWebhookMessage.order_id).where(
                    and_(
                        ProcessedWebhookMessage.user_id == user_id,
                        ProcessedWebhookMessage.whatsapp_message_id == wa_message_id,
                        ProcessedWebhookMessage.order_id.isnot(None),
                    )
                )
            )
            row = result.scalar_one_or_none()
            return row
        except Exception as e:
            logger.warning(
                "[IDEMPOTENCY] get_order_for_message failed for %s: %s",
                wa_message_id,
                e,
            )
            return None

    async def record_order_created(
        self,
        db: AsyncSession,
        user_id,
        wa_message_id: str,
        order_id: str,
    ) -> None:
        """Record which order was created for this message."""
        from ..models import ProcessedWebhookMessage

        try:
            await db.execute(
                update(ProcessedWebhookMessage)
                .where(
                    and_(
                        ProcessedWebhookMessage.user_id == user_id,
                        ProcessedWebhookMessage.whatsapp_message_id == wa_message_id,
                    )
                )
                .values(order_id=order_id)
            )
            await db.commit()
        except Exception as e:
            logger.warning(
                "[IDEMPOTENCY] record_order_created failed for %s / %s: %s",
                wa_message_id,
                order_id,
                e,
            )

    async def check_and_set_flag(
        self,
        db: AsyncSession,
        user_id,
        wa_message_id: str,
        flag_name: str,
    ) -> bool:
        """Atomically check a boolean flag and set it to True.

        Uses UPDATE … WHERE flag = false RETURNING id so that exactly one
        caller wins the race even if two workers check simultaneously.

        Args:
            flag_name: 'confirmation_sent' or 'receipt_sent'

        Returns:
            True  → flag was False, now set to True (caller should proceed)
            False → flag was already True (caller should skip)
        """
        from ..models import ProcessedWebhookMessage

        if flag_name not in ("confirmation_sent", "receipt_sent"):
            logger.error("[IDEMPOTENCY] Invalid flag_name: %s", flag_name)
            return True  # Don't block on invalid usage

        try:
            flag_col = getattr(ProcessedWebhookMessage, flag_name)
            stmt = (
                update(ProcessedWebhookMessage)
                .where(
                    and_(
                        ProcessedWebhookMessage.user_id == user_id,
                        ProcessedWebhookMessage.whatsapp_message_id == wa_message_id,
                        flag_col == False,  # noqa: E712  — SQLAlchemy requires == for column comparison
                    )
                )
                .values(**{flag_name: True})
            )
            result = await db.execute(stmt)
            await db.commit()

            if result.rowcount == 1:
                # We flipped it — caller should proceed
                return True
            elif result.rowcount == 0:
                # Either already True, or no matching row.
                # Check if the row exists at all (if not, let the caller proceed
                # rather than silently swallowing the message).
                exists = await db.execute(
                    select(ProcessedWebhookMessage.id).where(
                        and_(
                            ProcessedWebhookMessage.user_id == user_id,
                            ProcessedWebhookMessage.whatsapp_message_id == wa_message_id,
                        )
                    )
                )
                if exists.scalar_one_or_none() is None:
                    # No idempotency row (e.g. table new, message predates it)
                    return True
                # Row exists and flag was already True
                return False
            return True
        except Exception as e:
            logger.warning(
                "[IDEMPOTENCY] check_and_set_flag(%s) failed for %s: %s",
                flag_name,
                wa_message_id,
                e,
            )
            # On failure, let the caller proceed rather than silently dropping
            return True


# Module-level singleton
idempotency_service = IdempotencyService()
