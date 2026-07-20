"""Customer-facing M-Pesa STK result messages (EN / SW)."""

from __future__ import annotations

from typing import Dict, Tuple

# Daraja terminal failure codes — stop polling and notify customer
STK_TERMINAL_FAILURE_CODES = frozenset({"1032", "1037", "1", "2001", "17", "1001"})

_STK_MESSAGES: Dict[str, Tuple[str, str]] = {
    "1": (
        "Your M-Pesa balance is too low for this payment. Please top up and try again.",
        "Salio lako la M-Pesa halitoshi. Ongeza salio kisha ujaribu tena.",
    ),
    "2001": (
        "Incorrect M-Pesa PIN. Please try again carefully. If M-Pesa locked your line, wait a minute.",
        "PIN ya M-Pesa si sahihi. Jaribu tena kwa makini. Ikiwa M-Pesa imefunga laini, subiri dakika moja.",
    ),
    "1032": (
        "Payment was cancelled. Tap below when you're ready to pay for your order.",
        "Malipo yameghairiwa. Bonyeza hapa chini ukiwa tayari kulipa oda yako.",
    ),
    "1037": (
        "The payment request timed out. Tap below to send a new M-Pesa prompt.",
        "Ombi la malipo limekwisha muda. Bonyeza hapa chini kutuma ombi jipya la M-Pesa.",
    ),
    "17": (
        "Payment could not be completed. Tap below to try again or contact the business for help.",
        "Malipo hayakuweza kukamilika. Bonyeza hapa chini kujaribu tena au wasiliana na duka.",
    ),
    "1001": (
        "We could not process the payment request. Please try again shortly.",
        "Hatukuweza kushughulikia ombi la malipo. Tafadhali jaribu tena baadaye.",
    ),
}

_GENERIC_FAILURE = (
    "Payment was not completed. Tap below to try again.",
    "Malipo hayajakamilika. Bonyeza hapa chini kujaribu tena.",
)

_INCONCLUSIVE = (
    "We couldn't confirm your payment yet. If you entered your M-Pesa PIN, wait a minute. "
    "Otherwise tap below to try again.",
    "Hatujaweza kuthibitisha malipo bado. Ukiwa umeweka PIN ya M-Pesa, subiri dakika moja. "
    "Vinginevyo bonyeza hapa chini kujaribu tena.",
)

_API_ERROR = (
    "Couldn't reach M-Pesa right now. Please try again in a minute.",
    "Hatukuweza kuunganisha na M-Pesa kwa sasa. Tafadhali jaribu tena baada ya dakika moja.",
)


def stk_customer_message(
    result_code: str,
    *,
    lang: str = "en",
    result_desc: str = "",
) -> str:
    """Map Daraja result code to a friendly customer message."""
    code = str(result_code or "").strip()
    pair = _STK_MESSAGES.get(code, _GENERIC_FAILURE)
    msg = pair[1] if (lang or "en").lower().startswith("sw") else pair[0]
    if code not in _STK_MESSAGES and result_desc:
        return f"{msg} ({result_desc})"
    return msg


def stk_inconclusive_message(*, lang: str = "en") -> str:
    pair = _INCONCLUSIVE
    return pair[1] if (lang or "en").lower().startswith("sw") else pair[0]


def stk_api_error_message(*, lang: str = "en") -> str:
    pair = _API_ERROR
    return pair[1] if (lang or "en").startswith("sw") else pair[0]
