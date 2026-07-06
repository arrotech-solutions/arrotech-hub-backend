"""M-Pesa STK flow for rent collection (non-order payments)."""
from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models import User
from .cache_service import cache_service
from .daraja_service import DarajaService
from .rent_tenant_storage_service import rent_tenant_storage_service, storage_config_from_business

logger = logging.getLogger(__name__)


def _normalize_ke_phone(phone: str) -> str:
    cleaned = re.sub(r"\D", "", str(phone or ""))
    if cleaned.startswith("0"):
        return "254" + cleaned[1:]
    if cleaned.startswith("7") or cleaned.startswith("1"):
        if len(cleaned) == 9:
            return "254" + cleaned
    return cleaned


def rent_payment_reference(unit: str, period: Optional[str] = None) -> str:
    period = period or datetime.utcnow().strftime("%Y%m")
    unit_slug = re.sub(r"[^A-Za-z0-9]", "", str(unit or "UNIT"))[:8]
    return f"RENT-{unit_slug}-{period}"[:12]


async def initiate_rent_stk_payment(
    *,
    user: User,
    db: AsyncSession,
    amount: Any,
    unit: str,
    phone_number: str,
    session_key: str,
    business_config: Dict[str, Any],
    period: str = "",
    tenant_name: str = "",
) -> Dict[str, Any]:
    """Initiate STK push for rent; stores Redis mapping with payment_type=rent."""
    from .mpesa_reconciliation_service import MpesaReconciliationService
    from .order_tracking_service import order_tracking_service
    from ..models import MpesaAgentConfig

    if not unit:
        return {"success": False, "error": "Tenant unit is required for rent payment"}

    phone = _normalize_ke_phone(phone_number)
    try:
        amount_int = int(float(amount))
    except (TypeError, ValueError):
        amount_int = 0
    if amount_int < 1:
        return {"success": False, "error": "amount must be at least 1 KES"}

    res = await db.execute(select(MpesaAgentConfig).where(MpesaAgentConfig.user_id == user.id))
    cfg = res.scalar_one_or_none()
    if not cfg or not cfg.webhook_secret:
        return {"success": False, "error": "M-Pesa is not configured. Use Paybill instructions instead."}

    recon = MpesaReconciliationService()
    decrypted = recon.decrypt_config_credentials(cfg)
    if not decrypted.get("daraja_consumer_key") or not decrypted.get("daraja_consumer_secret"):
        return {"success": False, "error": "Daraja credentials missing in Settings → M-Pesa"}
    if not cfg.daraja_passkey or not cfg.daraja_shortcode:
        return {"success": False, "error": "Daraja passkey/shortcode missing"}

    ref = rent_payment_reference(unit, period[:7].replace(" ", "") if period else None)
    owner_id = order_tracking_service.owner_id_from_session_key(session_key or "", str(user.id))

    if order_tracking_service.is_stk_debounced(owner_id, ref):
        return {"success": False, "error": "Please wait a moment before requesting another M-Pesa prompt."}

    base_url = (cfg.callback_url_override or settings.API_BASE_URL).rstrip("/")
    callback_url = f"{base_url}/api/agents/daraja/callback/{cfg.webhook_secret}"
    tenant_env = (cfg.daraja_environment or "sandbox").lower()

    daraja = DarajaService(environment=tenant_env)
    stk_res = await daraja.stk_push(
        phone_number=phone,
        amount=amount_int,
        account_reference=ref,
        transaction_desc=f"Rent {unit}"[:13],
        callback_url=callback_url,
        consumer_key=decrypted["daraja_consumer_key"],
        consumer_secret=decrypted["daraja_consumer_secret"],
        short_code=cfg.daraja_shortcode,
        passkey=decrypted.get("daraja_passkey"),
    )
    if not stk_res.get("success"):
        return {"success": False, "error": stk_res.get("error", "STK push failed")}

    checkout_request_id = stk_res.get("checkout_request_id")
    merchant_request_id = stk_res.get("merchant_request_id")
    whatsapp_sender = phone
    if session_key and session_key.startswith("ccm:"):
        parts = session_key.split(":")
        if len(parts) >= 4:
            whatsapp_sender = parts[3] or whatsapp_sender

    storage_config = storage_config_from_business(business_config)
    payload = {
        "payment_type": "rent",
        "user_id": str(user.id),
        "session_key": session_key or "",
        "platform": "whatsapp",
        "sender_id": whatsapp_sender,
        "whatsapp_sender": whatsapp_sender,
        "customer_phone": phone,
        "mpesa_phone": phone,
        "order_id": ref,
        "tenant_unit": unit,
        "tenant_name": tenant_name,
        "amount": amount_int,
        "currency": business_config.get("currency", "KES"),
        "business_name": business_config.get("business_name")
        or business_config.get("property_name", ""),
        "business_phone": business_config.get("business_phone", ""),
        "landlord_name": business_config.get("landlord_name", ""),
        "storage_config": storage_config,
        "business_config_snapshot": dict(business_config),
        "period": period or datetime.utcnow().strftime("%B %Y"),
        "created_at": datetime.utcnow().isoformat(),
    }

    if checkout_request_id:
        cache_service.set(f"mpesa:stk:checkout:{checkout_request_id}", payload, expire_seconds=86400)
    if merchant_request_id:
        cache_service.set(f"mpesa:stk:merchant:{merchant_request_id}", payload, expire_seconds=86400)

    order_tracking_service.record_stk_context(
        owner_id,
        ref,
        checkout_request_id=checkout_request_id or "",
        merchant_request_id=merchant_request_id or "",
        amount=amount_int,
        whatsapp_sender=whatsapp_sender,
        customer_phone=phone,
    )

    return {
        "success": True,
        "result": (
            f"M-Pesa payment prompt sent to {phone}. "
            f"Please enter your PIN to pay KES {amount_int:,} for unit {unit}."
        ),
        "rent_reference": ref,
    }


async def _send_whatsapp_message(
    db: AsyncSession,
    owner_user_id: uuid.UUID,
    to_number: str,
    message: str,
) -> None:
    if not to_number or not message:
        return
    try:
        from ..models import Connection
        from .whatsapp_service import WhatsAppService

        conn_res = await db.execute(
            select(Connection).where(
                Connection.user_id == owner_user_id,
                Connection.platform == "whatsapp",
                Connection.status == "active",
            )
        )
        conn = conn_res.scalar_one_or_none()
        wa_config = conn.config if conn else None
        if wa_config:
            await WhatsAppService().send_message(to_number, message, config=wa_config)
    except Exception as exc:
        logger.warning("[RENT_STK] WhatsApp send failed: %s", exc)


async def finalize_rent_stk_payment(
    *,
    db: AsyncSession,
    owner_user_id: str,
    notify_ctx: Dict[str, Any],
    is_paid: bool,
    mpesa_receipt: str = "",
    amount_paid: float = 0.0,
    result_code: str = "",
    result_desc: str = "",
) -> None:
    """After STK callback: persist payment, notify tenant and landlord."""
    if not is_paid:
        return

    owner_uuid = uuid.UUID(str(owner_user_id))
    owner_res = await db.execute(select(User).where(User.id == owner_uuid))
    owner_user = owner_res.scalar_one_or_none()
    if not owner_user:
        return

    business_config = notify_ctx.get("business_config_snapshot") or {}
    unit = notify_ctx.get("tenant_unit") or ""
    tenant_name = notify_ctx.get("tenant_name") or "Tenant"
    whatsapp_sender = notify_ctx.get("whatsapp_sender") or notify_ctx.get("sender_id") or ""
    period = notify_ctx.get("period") or datetime.utcnow().strftime("%B %Y")
    currency = notify_ctx.get("currency") or "KES"

    from .rent_collection_service import rent_collection_service

    tenants = await rent_tenant_storage_service.load_tenants(owner_user, business_config, db)
    lookup = await rent_collection_service.lookup_tenant(
        phone_number=whatsapp_sender,
        unit=unit,
        tenants_data=tenants,
    )
    tenant = lookup.get("tenant") or {}
    tenant_name = tenant.get("name") or tenant_name
    unit = tenant.get("unit") or unit

    rent_amt = float(tenant.get("rent_amount") or 0)
    water_amt = float(tenant.get("water_amount") or 0)
    elec_amt = float(tenant.get("electricity_amount") or 0)
    garbage_amt = float(tenant.get("garbage_amount") or 0)
    total_bill = rent_amt + water_amt + elec_amt + garbage_amt
    if total_bill <= 0:
        total_bill = float(amount_paid or notify_ctx.get("amount") or 0)

    pay_res = await rent_collection_service.process_partial_payment(
        tenant_name=tenant_name,
        unit=unit,
        total_amount=total_bill,
        paid_amount=float(amount_paid or notify_ctx.get("amount") or 0),
        transaction_id=mpesa_receipt,
        period=period,
        currency=currency,
    )

    balance_after = float(pay_res.get("balance") or 0)
    await rent_tenant_storage_service.append_payment_row(
        owner_user,
        business_config,
        db,
        tenant_name=tenant_name,
        unit=unit,
        phone=whatsapp_sender,
        amount_paid=float(amount_paid or notify_ctx.get("amount") or 0),
        total_bill=total_bill,
        balance_after=balance_after,
        transaction_id=mpesa_receipt,
        method="M-Pesa STK",
        period=period,
    )
    await rent_tenant_storage_service.update_tenant_balance(
        owner_user, business_config, db, unit=unit, new_balance=balance_after
    )

    receipt_text = pay_res.get("message") or "Payment received. Thank you!"
    await _send_whatsapp_message(db, owner_uuid, whatsapp_sender, receipt_text)

    landlord_phone = business_config.get("business_phone") or ""
    landlord_msg = (
        f"💰 Rent payment received\n"
        f"Tenant: {tenant_name} ({unit})\n"
        f"Amount: {currency} {float(amount_paid or 0):,.0f}\n"
        f"Receipt: {mpesa_receipt or 'STK'}\n"
        f"Balance after: {currency} {balance_after:,.0f}"
    )
    await _send_whatsapp_message(db, owner_uuid, landlord_phone, landlord_msg)
