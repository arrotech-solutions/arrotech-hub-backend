"""
Authoritative subscription plan catalog for Arrotech Hub.
Single source of truth for tier slugs, prices, and billing periods.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..models import SubscriptionTier

YEARLY_DISCOUNT = 0.8  # 20% off annual billing

PLANS: Dict[str, Dict[str, Any]] = {
    SubscriptionTier.STARTER: {
        "monthly_kes": 1500,
        "yearly_kes": int(1500 * 12 * YEARLY_DISCOUNT),
        "name": "Starter",
        "tagline": "Unified Action",
    },
    SubscriptionTier.BUSINESS: {
        "monthly_kes": 5000,
        "yearly_kes": int(5000 * 12 * YEARLY_DISCOUNT),
        "name": "Business",
        "tagline": "Unified Operations",
    },
    SubscriptionTier.PRO: {
        "monthly_kes": 10000,
        "yearly_kes": int(10000 * 12 * YEARLY_DISCOUNT),
        "name": "Pro / Agency",
        "tagline": "Unified Command Center",
    },
}

# Map legacy / display names → canonical slug
PLAN_ALIASES: Dict[str, str] = {
    "lite": SubscriptionTier.STARTER,
    "starter": SubscriptionTier.STARTER,
    "unified action": SubscriptionTier.STARTER,
    "business": SubscriptionTier.BUSINESS,
    "unified operations": SubscriptionTier.BUSINESS,
    "pro": SubscriptionTier.PRO,
    "pro / agency": SubscriptionTier.PRO,
    "agency": SubscriptionTier.PRO,
    "unified command center": SubscriptionTier.PRO,
    "enterprise": SubscriptionTier.ENTERPRISE,
}

BILLING_CYCLES = ("monthly", "yearly")
PERIOD_DAYS = {"monthly": 30, "yearly": 365}
AMOUNT_TOLERANCE_KES = 1


def normalize_billing_cycle(raw: Optional[str]) -> str:
    cycle = (raw or "monthly").lower().strip()
    return cycle if cycle in BILLING_CYCLES else "monthly"


def normalize_plan_slug(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    key = raw.strip().lower()
    if key in PLANS:
        return key
    if key in PLAN_ALIASES:
        return PLAN_ALIASES[key]
    # Title-case display names e.g. "Starter"
    alias = PLAN_ALIASES.get(raw.strip().lower())
    if alias:
        return alias
    title_key = raw.strip().lower()
    return PLAN_ALIASES.get(title_key)


def get_price(plan_id: str, billing_cycle: str = "monthly") -> Optional[int]:
    plan = PLANS.get(plan_id)
    if not plan:
        return None
    cycle = normalize_billing_cycle(billing_cycle)
    return plan["yearly_kes"] if cycle == "yearly" else plan["monthly_kes"]


def get_period_days(billing_cycle: str = "monthly") -> int:
    return PERIOD_DAYS.get(normalize_billing_cycle(billing_cycle), 30)


def resolve_plan_from_amount(amount_kes: float, billing_cycle: str = "monthly") -> Optional[str]:
    """Infer plan from payment amount (within tolerance)."""
    cycle = normalize_billing_cycle(billing_cycle)
    amount = int(round(amount_kes))
    for plan_id, plan in PLANS.items():
        expected = plan["yearly_kes"] if cycle == "yearly" else plan["monthly_kes"]
        if abs(amount - expected) <= AMOUNT_TOLERANCE_KES:
            return plan_id
    # Fallback thresholds (monthly only) for legacy payments
    if cycle == "monthly":
        if amount >= 10000:
            return SubscriptionTier.PRO
        if amount >= 5000:
            return SubscriptionTier.BUSINESS
        if amount >= 1500:
            return SubscriptionTier.STARTER
    return None


def resolve_plan_slug(
    raw: Optional[str],
    amount_kes: float,
    billing_cycle: str = "monthly",
) -> Optional[str]:
    slug = normalize_plan_slug(raw)
    if slug and slug in PLANS:
        return slug
    # custom_fields may send display name with different casing
    if raw:
        for alias, canonical in PLAN_ALIASES.items():
            if alias == raw.strip().lower() or raw.strip().lower() == canonical:
                if canonical in PLANS:
                    return canonical
    return resolve_plan_from_amount(amount_kes, billing_cycle)


def validate_amount(plan_id: str, billing_cycle: str, amount_kes: float) -> bool:
    expected = get_price(plan_id, billing_cycle)
    if expected is None:
        return False
    return abs(int(round(amount_kes)) - expected) <= AMOUNT_TOLERANCE_KES


def list_plans_for_api() -> List[Dict[str, Any]]:
    """Public plan catalog for GET /subscription/plans."""
    result = []
    for plan_id, plan in PLANS.items():
        result.append({
            "id": plan_id,
            "name": plan["name"],
            "tagline": plan["tagline"],
            "monthly_kes": plan["monthly_kes"],
            "yearly_kes": plan["yearly_kes"],
            "yearly_discount_percent": int((1 - YEARLY_DISCOUNT) * 100),
        })
    return result


def get_yearly_price_from_monthly(monthly_kes: int) -> int:
    return int(monthly_kes * 12 * YEARLY_DISCOUNT)
