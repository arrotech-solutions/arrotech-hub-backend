"""WhatsApp Cloud API phone registration status helpers.

Meta phone `status` values (API) include at least:
CONNECTED, DISCONNECTED, PENDING, DELETED, MIGRATED, BANNED,
RESTRICTED, RATE_LIMITED, FLAGGED, UNKNOWN, UNVERIFIED.

WhatsApp Manager often labels DISCONNECTED as "Offline".
Only CONNECTED can send/receive Cloud API messages.
"""

from typing import Any, Optional

# Statuses where calling /register is the normal recovery path.
REGISTRATION_RECOVERY_STATUSES = frozenset({
    "PENDING",
    "DISCONNECTED",
    "UNVERIFIED",
    "UNKNOWN",
    "",
})


def normalize_phone_status(phone_status: Optional[str]) -> str:
    return (phone_status or "").strip().upper()


def phone_needs_cloud_registration(phone_status: Optional[str]) -> bool:
    """True when the number is not messaging-ready on Cloud API.

    Any non-CONNECTED status means Hub must not show a green Active/Deregister-only
    state. PENDING is only one of several offline/incomplete values.
    """
    return normalize_phone_status(phone_status) != "CONNECTED"


def phone_registration_is_primary_action(phone_status: Optional[str]) -> bool:
    """True when Complete Registration is the expected next tenant action."""
    status = normalize_phone_status(phone_status)
    return status != "CONNECTED" and (
        status in REGISTRATION_RECOVERY_STATUSES or status not in {
            "BANNED",
            "DELETED",
            "MIGRATED",
            "RESTRICTED",
            "RATE_LIMITED",
            "FLAGGED",
        }
    )


def is_already_deregistered_error(status_code: int, data: Any) -> bool:
    """Meta returns #100 when deregister is called on an already-offline number."""
    if status_code not in (400, 404):
        return False
    error = data.get("error") if isinstance(data, dict) else None
    if not isinstance(error, dict):
        return False
    code = error.get("code")
    message = str(error.get("message") or "").lower()
    return code == 100 or "invalid parameter" in message


def resolve_phone_status_from_meta_list(phones: list, phone_number_id: Optional[str]) -> str:
    """Pick Meta status for the Hub-linked phone number id."""
    if not phone_number_id:
        return "PENDING"
    for phone in phones or []:
        if str(phone.get("id")) == str(phone_number_id):
            return phone.get("status") or "PENDING"
    return "PENDING"
