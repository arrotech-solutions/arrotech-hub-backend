"""M-Pesa configuration helpers for rent collection agents."""
from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import MpesaAgentConfig


async def mpesa_live_ready(user_id: uuid.UUID, db: AsyncSession) -> bool:
    """True when property manager has live Daraja credentials (STK enabled)."""
    result = await db.execute(
        select(MpesaAgentConfig).where(MpesaAgentConfig.user_id == user_id)
    )
    cfg = result.scalar_one_or_none()
    if not cfg:
        return False
    if (cfg.daraja_environment or "sandbox").lower() != "live":
        return False
    if not cfg.webhook_secret:
        return False
    if not cfg.daraja_passkey or not cfg.daraja_shortcode:
        return False
    try:
        from .mpesa_reconciliation_service import MpesaReconciliationService

        decrypted = MpesaReconciliationService().decrypt_config_credentials(cfg)
        if not decrypted.get("daraja_consumer_key") or not decrypted.get("daraja_consumer_secret"):
            return False
    except Exception:
        return False
    return True
