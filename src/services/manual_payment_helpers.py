"""Helpers for the manual M-Pesa payment fallback (no STK push).

Used by the WhatsApp ordering agent when a business has not yet configured
working Daraja (STK) credentials. Instead of triggering an STK push, the agent
shows the customer the business's Paybill / Till / Pochi la Biashara / Send Money
details so they can pay from their own M-Pesa menu.
"""
from typing import Any, Dict, Optional


def _clean(value: Any) -> str:
    return str(value).strip() if value not in (None, "") else ""


def stk_credentials_ready(cfg: Any, decrypted: Optional[Dict[str, Any]] = None) -> bool:
    """True when the business has a full set of Daraja STK credentials.

    Mirrors the runtime checks in ``_sub_initiate_mpesa_payment``: a webhook
    secret, consumer key/secret, passkey and shortcode must all be present.
    ``decrypted`` is the output of ``MpesaReconciliationService.decrypt_config_credentials``.
    """
    if not cfg:
        return False
    if not _clean(getattr(cfg, "webhook_secret", "")):
        return False
    if not _clean(getattr(cfg, "daraja_shortcode", "")):
        return False
    if not _clean(getattr(cfg, "daraja_passkey", "")):
        return False

    decrypted = decrypted or {}
    if not _clean(decrypted.get("daraja_consumer_key")):
        return False
    if not _clean(decrypted.get("daraja_consumer_secret")):
        return False
    return True


def manual_payment_configured(cfg: Any) -> bool:
    """True when manual payment is enabled and at least one method is set."""
    if not cfg:
        return False
    if not bool(getattr(cfg, "manual_payment_enabled", False)):
        return False
    return any(
        _clean(getattr(cfg, field, ""))
        for field in (
            "manual_paybill_number",
            "manual_till_number",
            "manual_pochi_number",
            "manual_send_money_number",
        )
    )


def _format_amount(amount: Any, currency: str = "KES") -> str:
    try:
        amt = int(float(amount))
        if amt >= 1:
            return f"{currency} {amt:,}"
    except (TypeError, ValueError):
        pass
    return ""


def build_manual_payment_message(
    cfg: Any,
    *,
    order_id: str,
    amount: Any,
    business_name: str = "",
    currency: str = "KES",
    lang: str = "en",
) -> str:
    """Build bilingual step-by-step manual payment instructions for the customer."""
    is_sw = (lang or "en").lower().startswith("sw")

    paybill = _clean(getattr(cfg, "manual_paybill_number", ""))
    paybill_account = _clean(getattr(cfg, "manual_paybill_account", "")) or _clean(order_id) or "your order number"
    till = _clean(getattr(cfg, "manual_till_number", ""))
    pochi = _clean(getattr(cfg, "manual_pochi_number", ""))
    send_money = _clean(getattr(cfg, "manual_send_money_number", ""))
    recipient = _clean(getattr(cfg, "manual_recipient_name", "")) or _clean(business_name)
    note = _clean(getattr(cfg, "manual_payment_note", ""))
    amount_str = _format_amount(amount, currency)

    blocks = []

    if is_sw:
        header = "💳 *Njia za malipo ya M-Pesa*"
        if amount_str:
            header += f"\nKiasi: *{amount_str}*"
        blocks.append(header)

        if paybill:
            blocks.append(
                "*Pay Bill*\n"
                "1. Nenda M-Pesa > Lipa na M-Pesa > Pay Bill\n"
                f"2. Nambari ya Biashara: *{paybill}*\n"
                f"3. Akaunti: *{paybill_account}*\n"
                + (f"4. Kiasi: *{amount_str}*\n" if amount_str else "")
                + "5. Weka PIN yako na uthibitishe"
            )
        if till:
            blocks.append(
                "*Buy Goods (Till)*\n"
                "1. Nenda M-Pesa > Lipa na M-Pesa > Buy Goods and Services\n"
                f"2. Nambari ya Till: *{till}*\n"
                + (f"3. Kiasi: *{amount_str}*\n" if amount_str else "")
                + "4. Weka PIN yako na uthibitishe"
            )
        if pochi:
            blocks.append(
                "*Pochi la Biashara*\n"
                "1. Nenda M-Pesa > Tuma Pesa (Send Money)\n"
                f"2. Nambari: *{pochi}*"
                + (f" ({recipient})" if recipient else "")
                + "\n"
                + (f"3. Kiasi: *{amount_str}*\n" if amount_str else "")
                + "4. Weka PIN yako na uthibitishe"
            )
        if send_money:
            blocks.append(
                "*Tuma Pesa (Send Money)*\n"
                "1. Nenda M-Pesa > Tuma Pesa (Send Money)\n"
                f"2. Nambari: *{send_money}*"
                + (f" ({recipient})" if recipient else "")
                + "\n"
                + (f"3. Kiasi: *{amount_str}*\n" if amount_str else "")
                + "4. Weka PIN yako na uthibitishe"
            )
        if note:
            blocks.append(f"📝 {note}")
        blocks.append(
            "Baada ya kulipa, tafadhali *tuma msimbo wa uthibitisho wa M-Pesa* hapa (mf. QGR7XXXX) "
            "ili biashara ithibitishe oda yako. 🙏"
        )
    else:
        header = "💳 *M-Pesa payment options*"
        if amount_str:
            header += f"\nAmount: *{amount_str}*"
        blocks.append(header)

        if paybill:
            blocks.append(
                "*Pay Bill*\n"
                "1. Go to M-Pesa > Lipa na M-Pesa > Pay Bill\n"
                f"2. Business no: *{paybill}*\n"
                f"3. Account no: *{paybill_account}*\n"
                + (f"4. Amount: *{amount_str}*\n" if amount_str else "")
                + "5. Enter your PIN and confirm"
            )
        if till:
            blocks.append(
                "*Buy Goods (Till)*\n"
                "1. Go to M-Pesa > Lipa na M-Pesa > Buy Goods and Services\n"
                f"2. Till no: *{till}*\n"
                + (f"3. Amount: *{amount_str}*\n" if amount_str else "")
                + "4. Enter your PIN and confirm"
            )
        if pochi:
            blocks.append(
                "*Pochi la Biashara*\n"
                "1. Go to M-Pesa > Send Money\n"
                f"2. Number: *{pochi}*"
                + (f" ({recipient})" if recipient else "")
                + "\n"
                + (f"3. Amount: *{amount_str}*\n" if amount_str else "")
                + "4. Enter your PIN and confirm"
            )
        if send_money:
            blocks.append(
                "*Send Money*\n"
                "1. Go to M-Pesa > Send Money\n"
                f"2. Number: *{send_money}*"
                + (f" ({recipient})" if recipient else "")
                + "\n"
                + (f"3. Amount: *{amount_str}*\n" if amount_str else "")
                + "4. Enter your PIN and confirm"
            )
        if note:
            blocks.append(f"📝 {note}")
        blocks.append(
            "After paying, please *send the M-Pesa confirmation code* here (e.g. QGR7XXXX) "
            "so the business can confirm your order. 🙏"
        )

    return "\n\n".join(b for b in blocks if b)
