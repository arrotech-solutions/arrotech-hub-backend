"""Load, merge, validate, and persist per-merchant commerce policy."""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
from typing import Any, Dict, List, Optional, Set
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import CommercePolicy
from .order_service import DELIVERY_METHODS, ORDER_STATUSES
from .whatsapp_ordering_helpers import VALID_DELIVERY_METHODS

SELL_MODES = frozenset(
    {"retail", "food", "clothing", "grocery", "pharmacy", "custom"}
)

DEFAULT_COMMERCE_POLICY: Dict[str, Any] = {
    "sell_modes": ["retail", "food"],
    "delivery_methods": ["delivery", "pickup"],
    "reservations_enabled": False,
    "business_hours": {},
    "away_message": "",
    "return_window_days": 7,
    "return_reason_codes": [
        "damaged",
        "wrong_item",
        "not_as_described",
        "changed_mind",
    ],
    "auto_approve_enabled": False,
    "auto_approve_max_amount_kes": 0,
    "cancel_until_status": "preparing",
    "human_handoff_ttl_hours": 24,
    "commerce_rails_enabled": True,
}

_POLICY_KEYS = frozenset(DEFAULT_COMMERCE_POLICY.keys())
_CANCEL_UNTIL_STATUSES = frozenset(ORDER_STATUSES)


class CommercePolicyValidationError(ValueError):
    """Raised when merchant policy fields fail validation."""


def _merge_policy(stored: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    merged = deepcopy(DEFAULT_COMMERCE_POLICY)
    if not stored or not isinstance(stored, dict):
        return merged
    for key, value in stored.items():
        if key in _POLICY_KEYS:
            merged[key] = value
    return merged


def _coerce_bool(value: Any, field: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "on"}:
            return True
        if lowered in {"false", "0", "no", "off"}:
            return False
    raise CommercePolicyValidationError(f"{field} must be a boolean")


def _coerce_nonneg_int(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise CommercePolicyValidationError(f"{field} must be a non-negative integer")
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise CommercePolicyValidationError(
            f"{field} must be a non-negative integer"
        ) from exc
    if number < 0:
        raise CommercePolicyValidationError(f"{field} must be >= 0")
    return number


def _coerce_positive_int(value: Any, field: str) -> int:
    number = _coerce_nonneg_int(value, field)
    if number <= 0:
        raise CommercePolicyValidationError(f"{field} must be > 0")
    return number


def _coerce_nonneg_amount(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise CommercePolicyValidationError(f"{field} must be a non-negative amount")
    if isinstance(value, Decimal):
        amount = float(value)
    elif isinstance(value, (int, float)):
        amount = float(value)
    else:
        try:
            amount = float(str(value).strip())
        except (TypeError, ValueError) as exc:
            raise CommercePolicyValidationError(
                f"{field} must be a non-negative amount"
            ) from exc
    if amount < 0:
        raise CommercePolicyValidationError(f"{field} must be >= 0")
    return amount


def _coerce_string_list(
    value: Any,
    field: str,
    allowed: Optional[Set[str]] = None,
) -> List[str]:
    if not isinstance(value, list):
        raise CommercePolicyValidationError(f"{field} must be a list")
    cleaned: List[str] = []
    for item in value:
        text = str(item).strip().lower()
        if not text:
            continue
        if allowed is not None and text not in allowed:
            raise CommercePolicyValidationError(
                f"Invalid {field} value '{text}'. Allowed: {', '.join(sorted(allowed))}"
            )
        cleaned.append(text)
    if not cleaned:
        raise CommercePolicyValidationError(f"{field} must not be empty")
    return cleaned


def _coerce_reason_codes(value: Any, field: str) -> List[str]:
    if not isinstance(value, list):
        raise CommercePolicyValidationError(f"{field} must be a list")
    codes: List[str] = []
    for item in value:
        text = str(item).strip()
        if not text:
            continue
        codes.append(text)
    if not codes:
        raise CommercePolicyValidationError(f"{field} must not be empty")
    return codes


def _validate_policy(policy: Dict[str, Any]) -> Dict[str, Any]:
    validated = deepcopy(DEFAULT_COMMERCE_POLICY)
    validated["sell_modes"] = _coerce_string_list(
        policy.get("sell_modes"),
        "sell_modes",
        set(SELL_MODES),
    )
    delivery_allowed = set(DELIVERY_METHODS) | set(VALID_DELIVERY_METHODS)
    validated["delivery_methods"] = _coerce_string_list(
        policy.get("delivery_methods"),
        "delivery_methods",
        delivery_allowed,
    )
    validated["reservations_enabled"] = _coerce_bool(
        policy.get("reservations_enabled"),
        "reservations_enabled",
    )
    business_hours = policy.get("business_hours")
    if business_hours is None:
        validated["business_hours"] = {}
    elif not isinstance(business_hours, dict):
        raise CommercePolicyValidationError("business_hours must be an object")
    else:
        validated["business_hours"] = business_hours

    away = policy.get("away_message")
    validated["away_message"] = "" if away is None else str(away)
    validated["return_window_days"] = _coerce_nonneg_int(
        policy.get("return_window_days"),
        "return_window_days",
    )
    validated["return_reason_codes"] = _coerce_reason_codes(
        policy.get("return_reason_codes"),
        "return_reason_codes",
    )
    validated["auto_approve_enabled"] = _coerce_bool(
        policy.get("auto_approve_enabled"),
        "auto_approve_enabled",
    )
    validated["auto_approve_max_amount_kes"] = _coerce_nonneg_amount(
        policy.get("auto_approve_max_amount_kes"),
        "auto_approve_max_amount_kes",
    )
    cancel = str(policy.get("cancel_until_status", "")).strip().lower()
    if cancel not in _CANCEL_UNTIL_STATUSES:
        raise CommercePolicyValidationError(
            f"cancel_until_status must be one of: {', '.join(ORDER_STATUSES)}"
        )
    validated["cancel_until_status"] = cancel
    validated["human_handoff_ttl_hours"] = _coerce_positive_int(
        policy.get("human_handoff_ttl_hours"),
        "human_handoff_ttl_hours",
    )
    validated["commerce_rails_enabled"] = _coerce_bool(
        policy.get("commerce_rails_enabled"),
        "commerce_rails_enabled",
    )
    return validated


def _normalize_patch(patch: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(patch, dict):
        raise CommercePolicyValidationError("Policy body must be an object")
    unknown = set(patch.keys()) - _POLICY_KEYS
    if unknown:
        raise CommercePolicyValidationError(
            f"Unknown policy fields: {', '.join(sorted(unknown))}"
        )
    return dict(patch)


async def _load_stored_config(
    db: AsyncSession,
    user_id: UUID,
) -> Optional[Dict[str, Any]]:
    result = await db.execute(
        select(CommercePolicy).where(CommercePolicy.user_id == user_id)
    )
    row = result.scalar_one_or_none()
    if row is None:
        return None
    config = row.config
    return dict(config) if isinstance(config, dict) else {}


async def get_policy(db: AsyncSession, user_id: UUID) -> Dict[str, Any]:
    """Return effective policy (defaults merged with stored overrides)."""
    stored = await _load_stored_config(db, user_id)
    merged = _merge_policy(stored)
    return _validate_policy(merged)


async def upsert_policy(
    db: AsyncSession,
    user_id: UUID,
    patch: Dict[str, Any],
) -> Dict[str, Any]:
    """Validate and persist policy overrides; return merged effective policy."""
    patch = _normalize_patch(patch)
    stored = await _load_stored_config(db, user_id) or {}
    candidate = _merge_policy({**stored, **patch})
    effective = _validate_policy(candidate)

    persisted = {key: effective[key] for key in patch}
    new_stored = {**stored, **persisted}

    result = await db.execute(
        select(CommercePolicy).where(CommercePolicy.user_id == user_id)
    )
    row = result.scalar_one_or_none()
    if row is None:
        row = CommercePolicy(user_id=user_id, config=new_stored)
        db.add(row)
    else:
        row.config = new_stored
    await db.commit()
    await db.refresh(row)
    return effective