"""Session commerce state for the ordering rails."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class CommerceState:
    cart_lines: list
    fulfillment_method: Optional[str] = None
    checkout_fields: dict = field(default_factory=dict)
    order_id: Optional[str] = None
    payment_status: Optional[str] = None
    phase: str = "cart"

    def copy(self) -> "CommerceState":
        return CommerceState(
            cart_lines=[dict(line) for line in self.cart_lines],
            fulfillment_method=self.fulfillment_method,
            checkout_fields=dict(self.checkout_fields),
            order_id=self.order_id,
            payment_status=self.payment_status,
            phase=self.phase,
        )
