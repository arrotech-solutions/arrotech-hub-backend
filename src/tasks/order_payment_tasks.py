"""
Celery tasks for unpaid order expiry and payment maintenance.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import select

from src.celery_app import app
from src.tasks.utils import run_async

logger = logging.getLogger(__name__)


@app.task(name="src.tasks.order_payment_tasks.expire_unpaid_orders_task")
def expire_unpaid_orders_task():
    """Cancel pending orders that were never paid within the TTL window."""

    async def _run():
        from src.database import get_session_maker
        from src.models import StkOrderMapping, User
        from src.services.order_tracking_service import (
            UNPAID_ORDER_TTL_HOURS,
            order_tracking_service,
        )

        cutoff = datetime.utcnow() - timedelta(hours=UNPAID_ORDER_TTL_HOURS)
        session_maker = get_session_maker()
        async with session_maker() as db:
            res = await db.execute(
                select(StkOrderMapping).where(
                    StkOrderMapping.payment_notified.is_(False),
                    StkOrderMapping.created_at < cutoff,
                )
            )
            rows = res.scalars().all()
            for row in rows:
                row.payment_notified = True
                owner_id = str(row.user_id)
                order_id = row.order_id
                registry = order_tracking_service.get_registered_order(owner_id, order_id) or {}
                if registry.get("payment_notified"):
                    continue
                registry["status"] = "cancelled"
                order_tracking_service._save_registry(owner_id, order_id, registry)

                owner_res = await db.execute(select(User).where(User.id == row.user_id))
                owner = owner_res.scalar_one_or_none()
                phone = row.whatsapp_sender or registry.get("customer_phone")
                if owner and phone:
                    wa_config = await order_tracking_service._get_whatsapp_config(owner, db)
                    if wa_config:
                        from src.services.whatsapp_service import WhatsAppService

                        msg = (
                            f"Your order *{order_id}* expired without payment. "
                            "Reply here if you'd like to place a new order."
                        )
                        wa = WhatsAppService()
                        await wa.send_message(phone, msg, config=wa_config)

                storage_config = row.storage_config or {}
                if storage_config.get("provider") == "google_sheets":
                    try:
                        from src.services.conversational_agent_service import ConversationalAgentService

                        conv = ConversationalAgentService()
                        from src.services.tool_executor import ToolExecutor

                        executor = ToolExecutor()
                        await conv._update_order_status_in_google_sheets(
                            executor,
                            order_id,
                            "cancelled",
                            storage_config,
                            owner,
                            db,
                        )
                    except Exception as sheet_err:
                        logger.warning(
                            "[ORDER_EXPIRE] Sheets update failed for %s: %s",
                            order_id,
                            sheet_err,
                        )
                logger.info("[ORDER_EXPIRE] Expired unpaid order %s", order_id)
            
            if rows:
                await db.commit()

    run_async(_run())
    return {"status": "completed"}
