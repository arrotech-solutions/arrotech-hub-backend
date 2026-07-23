"""
Order Management Service for Arrotech Hub.

Stateless processing tools for order capture, validation, and formatting.
No database models — data flows through workflow variables.
Designed for food orders, clothing orders, shop purchases, and more.
Users connect their own databases (Airtable, Google Sheets, etc.) for persistence.
"""

import logging
import re
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# Valid order statuses and their allowed transitions
ORDER_STATUSES = [
    "pending", "confirmed", "preparing", "ready",
    "shipped", "out_for_delivery", "delivered", "cancelled", "refunded"
]

STATUS_TRANSITIONS = {
    "pending": ["confirmed", "cancelled"],
    "confirmed": ["preparing", "cancelled"],
    "preparing": ["ready", "cancelled"],
    "ready": ["shipped", "out_for_delivery", "delivered", "cancelled"],
    "shipped": ["out_for_delivery", "delivered", "cancelled"],
    "out_for_delivery": ["delivered", "cancelled"],
    "delivered": ["refunded"],
    "cancelled": ["refunded"],
    "refunded": [],
}

ORDER_TYPES = ["food", "clothing", "retail", "grocery", "pharmacy", "real_estate", "custom"]

DELIVERY_METHODS = ["pickup", "delivery", "dine_in", "shipping", "digital"]


class OrderService:
    """Stateless order processing tools for workflow building blocks."""

    def __init__(self):
        pass

    async def handle_operation(
        self,
        operation: str,
        **kwargs
    ) -> Dict[str, Any]:
        """Route to the appropriate order tool."""
        try:
            kwargs = self._coerce_types(kwargs)

            if operation == "create_order":
                return await self.create_order(**kwargs)
            elif operation == "update_order_status":
                return await self.update_order_status(**kwargs)
            elif operation == "get_orders":
                return await self.get_orders(**kwargs)
            elif operation == "capture_customer_input":
                return await self.capture_customer_input(**kwargs)
            elif operation == "validate_order":
                return await self.validate_order(**kwargs)
            elif operation == "cancel_order":
                return await self.cancel_order(**kwargs)
            elif operation == "calculate_order_total":
                return await self.calculate_order_total(**kwargs)
            elif operation == "format_order_receipt":
                return await self.format_order_receipt(**kwargs)
            elif operation == "format_order_notification":
                return await self.format_order_notification(**kwargs)
            else:
                return {"success": False, "error": f"Unknown operation: {operation}"}
        except Exception as e:
            logger.error(f"Order service error ({operation}): {e}")
            return {"success": False, "error": str(e)}

    @staticmethod
    def _coerce_types(kwargs: Dict[str, Any]) -> Dict[str, Any]:
        """Coerce string values from workflow variables to proper types."""
        float_fields = {
            "price", "amount", "total", "subtotal", "tax_amount",
            "discount", "discount_amount", "delivery_fee", "tax_rate",
            "unit_price", "weight",
        }
        int_fields = {"quantity", "max_results", "limit"}

        coerced = {}
        for key, value in kwargs.items():
            if value is None or value == "":
                coerced[key] = value
                continue

            if key in float_fields and isinstance(value, str):
                try:
                    coerced[key] = float(value.replace(",", ""))
                except (ValueError, AttributeError):
                    coerced[key] = 0.0
            elif key in int_fields and isinstance(value, str):
                try:
                    coerced[key] = int(float(value.replace(",", "")))
                except (ValueError, AttributeError):
                    coerced[key] = 0
            else:
                coerced[key] = value

        return coerced

    # ──────────────────────────────────────────────────────────────
    # 1. CREATE ORDER
    # ──────────────────────────────────────────────────────────────

    async def create_order(
        self,
        customer_name: str = "",
        customer_phone: str = "",
        customer_email: str = "",
        items: List[Dict[str, Any]] = None,
        order_type: str = "retail",
        delivery_method: str = "delivery",
        delivery_address: str = "",
        table_number: str = "",
        notes: str = "",
        currency: str = "KES",
        **kwargs
    ) -> Dict[str, Any]:
        """
        Create a structured order object ready for storage.

        Items format:
        [
            {"name": "Ribeye Steak", "quantity": 2, "unit_price": 1500, "unit": "kg"},
            {"name": "T-Shirt (L, Blue)", "quantity": 1, "unit_price": 800},
        ]
        """
        if not customer_name:
            return {"success": False, "error": "Customer name is required"}
        if not items or len(items) == 0:
            return {"success": False, "error": "At least one item is required"}

        # Validate order type
        if order_type not in ORDER_TYPES:
            order_type = "custom"

        # Validate delivery method
        if delivery_method not in DELIVERY_METHODS:
            delivery_method = "delivery"

        # Generate order ID
        now = datetime.now()
        order_id = f"ORD-{now.strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"

        # Process items
        processed_items = []
        subtotal = 0.0
        for i, item in enumerate(items):
            item_name = item.get("name", f"Item {i + 1}")
            quantity = float(item.get("quantity", 1))
            unit_price = float(item.get("unit_price", item.get("price", 0)) or 0)
            unit = item.get("unit", "pcs")
            item_total = quantity * unit_price

            processed_items.append({
                "item_number": i + 1,
                "name": item_name,
                "quantity": quantity,
                "unit": unit,
                "unit_price": unit_price,
                "total": round(item_total, 2),
                # Carry forward variant info
                "size": item.get("size"),
                "color": item.get("color"),
                "weight": item.get("weight"),
                "cut": item.get("cut"),
                "notes": item.get("notes"),
            })
            subtotal += item_total

        order_data = {
            "order_id": order_id,
            "status": "pending",
            "order_type": order_type,
            "customer": {
                "name": customer_name,
                "phone": customer_phone,
                "email": customer_email,
            },
            "items": processed_items,
            "item_count": len(processed_items),
            "subtotal": round(subtotal, 2),
            "currency": currency,
            "delivery_method": delivery_method,
            "delivery_address": delivery_address,
            "table_number": table_number,
            "notes": notes,
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
        }

        return {
            "success": True,
            "order": order_data,
            "order_id": order_id,
            "subtotal": round(subtotal, 2),
            "item_count": len(processed_items),
            "message": f"Order {order_id} created for {customer_name} with {len(processed_items)} item(s) — {currency} {subtotal:,.2f}",
        }

    # ──────────────────────────────────────────────────────────────
    # 2. UPDATE ORDER STATUS
    # ──────────────────────────────────────────────────────────────

    async def update_order_status(
        self,
        order_id: str = "",
        new_status: str = "",
        current_status: str = "pending",
        updated_by: str = "",
        notes: str = "",
        **kwargs
    ) -> Dict[str, Any]:
        """Update order status with transition validation."""
        if not order_id:
            return {"success": False, "error": "Order ID is required"}
        if not new_status:
            return {"success": False, "error": "New status is required"}

        new_status = new_status.lower().replace(" ", "_")

        if new_status not in ORDER_STATUSES:
            return {
                "success": False,
                "error": f"Invalid status: '{new_status}'. Valid statuses: {', '.join(ORDER_STATUSES)}",
            }

        # Validate transition
        allowed = STATUS_TRANSITIONS.get(current_status, [])
        if allowed and new_status not in allowed:
            return {
                "success": False,
                "error": f"Cannot transition from '{current_status}' to '{new_status}'. Allowed: {', '.join(allowed)}",
                "current_status": current_status,
                "allowed_transitions": allowed,
            }

        now = datetime.now()
        status_icon = {
            "pending": "🕐",
            "confirmed": "✅",
            "preparing": "👨‍🍳",
            "ready": "📦",
            "shipped": "🚚",
            "out_for_delivery": "🏍️",
            "delivered": "✅",
            "cancelled": "❌",
            "refunded": "💰",
        }.get(new_status, "📋")

        return {
            "success": True,
            "order_id": order_id,
            "previous_status": current_status,
            "new_status": new_status,
            "status_icon": status_icon,
            "updated_at": now.isoformat(),
            "updated_by": updated_by or "system",
            "notes": notes,
            "message": f"{status_icon} Order {order_id} status updated: {current_status} → {new_status}",
        }

    # ──────────────────────────────────────────────────────────────
    # 3. GET ORDERS
    # ──────────────────────────────────────────────────────────────

    async def get_orders(
        self,
        status: str = "all",
        order_type: str = "",
        customer_name: str = "",
        date_from: str = "",
        date_to: str = "",
        limit: int = 20,
        sort_by: str = "created_at",
        sort_order: str = "desc",
        **kwargs
    ) -> Dict[str, Any]:
        """
        Build a structured query/filter object for retrieving orders.

        Since we don't store orders, this returns a filter specification
        that the user's connected database adapter can execute.
        """
        filters = {}

        if status and status != "all":
            if status in ORDER_STATUSES:
                filters["status"] = status
            else:
                return {"success": False, "error": f"Invalid status filter: '{status}'. Valid: {', '.join(ORDER_STATUSES + ['all'])}"}

        if order_type:
            if order_type in ORDER_TYPES:
                filters["order_type"] = order_type
            else:
                filters["order_type"] = order_type  # Allow custom types

        if customer_name:
            filters["customer_name"] = customer_name

        if date_from:
            filters["date_from"] = date_from
        if date_to:
            filters["date_to"] = date_to

        filter_description_parts = []
        if filters.get("status"):
            filter_description_parts.append(f"status={filters['status']}")
        if filters.get("order_type"):
            filter_description_parts.append(f"type={filters['order_type']}")
        if filters.get("customer_name"):
            filter_description_parts.append(f"customer='{filters['customer_name']}'")
        if filters.get("date_from"):
            filter_description_parts.append(f"from={filters['date_from']}")
        if filters.get("date_to"):
            filter_description_parts.append(f"to={filters['date_to']}")

        filter_description = ", ".join(filter_description_parts) if filter_description_parts else "all orders"

        return {
            "success": True,
            "filters": filters,
            "limit": min(limit, 100),
            "sort_by": sort_by,
            "sort_order": sort_order,
            "filter_description": filter_description,
            "message": f"Query built for orders: {filter_description} (limit: {min(limit, 100)}, sort: {sort_by} {sort_order})",
            "note": "Connect a database (Airtable, Google Sheets, or custom DB) to execute this query against your order data.",
        }

    # ──────────────────────────────────────────────────────────────
    # 4. CAPTURE CUSTOMER INPUT
    # ──────────────────────────────────────────────────────────────

    async def capture_customer_input(
        self,
        fields: Dict[str, Any] = None,
        form_type: str = "order",
        required_fields: List[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Capture and structure customer form data.
        Validates required fields and formats the data for storage.

        form_type: order, contact, feedback, inquiry, registration
        """
        if not fields:
            return {"success": False, "error": "Fields data is required"}

        if required_fields is None:
            # Default required fields based on form type
            required_fields = {
                "order": ["name", "phone"],
                "contact": ["name", "phone"],
                "feedback": ["name", "message"],
                "inquiry": ["name", "message"],
                "registration": ["name", "email", "phone"],
            }.get(form_type, ["name"])

        # Validate required fields
        missing_fields = [f for f in required_fields if not fields.get(f)]
        if missing_fields:
            return {
                "success": False,
                "error": f"Missing required fields: {', '.join(missing_fields)}",
                "missing_fields": missing_fields,
                "provided_fields": list(fields.keys()),
            }

        # Validate phone format (if provided)
        phone = fields.get("phone", "")
        if phone:
            cleaned_phone = re.sub(r"[^\d+]", "", phone)
            if len(cleaned_phone) < 9:
                return {"success": False, "error": f"Invalid phone number: '{phone}'"}
            fields["phone_formatted"] = cleaned_phone

        # Validate email format (if provided)
        email = fields.get("email", "")
        if email:
            email_pattern = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")
            if not email_pattern.match(email):
                return {"success": False, "error": f"Invalid email: '{email}'"}

        now = datetime.now()
        submission_id = f"SUB-{now.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:4].upper()}"

        structured_data = {
            "submission_id": submission_id,
            "form_type": form_type,
            "fields": fields,
            "submitted_at": now.isoformat(),
            "field_count": len(fields),
        }

        return {
            "success": True,
            "submission": structured_data,
            "submission_id": submission_id,
            "field_count": len(fields),
            "message": f"Customer input captured ({form_type} form, {len(fields)} fields) — ID: {submission_id}",
        }

    # ──────────────────────────────────────────────────────────────
    # 5. VALIDATE ORDER
    # ──────────────────────────────────────────────────────────────

    async def validate_order(
        self,
        order_data: Dict[str, Any] = None,
        order_type: str = "",
        rules: Dict[str, Any] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Validate order data for completeness and business rules.
        Industry-specific validation for food, clothing, retail.
        """
        if not order_data:
            return {"success": False, "error": "Order data is required for validation"}

        errors = []
        warnings = []

        # Basic validations
        if not order_data.get("customer", {}).get("name"):
            errors.append("Customer name is missing")
        if not order_data.get("items") or len(order_data.get("items", [])) == 0:
            errors.append("Order has no items")

        # Validate items
        items = order_data.get("items", [])
        for i, item in enumerate(items):
            item_label = item.get("name", f"Item {i + 1}")
            if not item.get("name"):
                errors.append(f"Item {i + 1}: Missing name")
            if not item.get("unit_price") and item.get("unit_price") != 0:
                errors.append(f"Item '{item_label}': Missing unit price")
            if not item.get("quantity") and item.get("quantity") != 0:
                warnings.append(f"Item '{item_label}': Quantity not specified, defaulting to 1")
            if item.get("unit_price", 0) < 0:
                errors.append(f"Item '{item_label}': Negative price ({item.get('unit_price')})")
            if item.get("quantity", 0) < 0:
                errors.append(f"Item '{item_label}': Negative quantity ({item.get('quantity')})")

        # Industry-specific validations
        detected_type = order_type or order_data.get("order_type", "retail")

        if detected_type == "food":
            for i, item in enumerate(items):
                item_label = item.get("name", f"Item {i + 1}")
                # Food items may need weight
                if item.get("unit") == "kg" and not item.get("weight") and not item.get("quantity"):
                    warnings.append(f"Item '{item_label}': Weight not specified for kg-based item")

        elif detected_type == "clothing":
            for i, item in enumerate(items):
                item_label = item.get("name", f"Item {i + 1}")
                if not item.get("size"):
                    warnings.append(f"Item '{item_label}': Size not specified")
                if not item.get("color"):
                    warnings.append(f"Item '{item_label}': Color not specified")

        # Custom rules
        if rules:
            min_order = rules.get("min_order_amount")
            if min_order:
                subtotal = order_data.get("subtotal", 0)
                if subtotal < float(min_order):
                    errors.append(f"Order total ({subtotal}) below minimum ({min_order})")

            max_items = rules.get("max_items")
            if max_items and len(items) > int(max_items):
                errors.append(f"Too many items ({len(items)}), maximum is {max_items}")

            required_phone = rules.get("require_phone", False)
            if required_phone and not order_data.get("customer", {}).get("phone"):
                errors.append("Customer phone is required")

            required_address = rules.get("require_delivery_address", False)
            delivery_method = order_data.get("delivery_method", "")
            if required_address and delivery_method == "delivery" and not order_data.get("delivery_address"):
                errors.append("Delivery address is required for delivery orders")

        is_valid = len(errors) == 0

        return {
            "success": True,
            "is_valid": is_valid,
            "errors": errors,
            "warnings": warnings,
            "error_count": len(errors),
            "warning_count": len(warnings),
            "order_type": detected_type,
            "message": (
                f"✅ Order validation passed ({len(warnings)} warning(s))"
                if is_valid
                else f"❌ Order validation failed: {len(errors)} error(s), {len(warnings)} warning(s)"
            ),
        }

    # ──────────────────────────────────────────────────────────────
    # 6. CANCEL ORDER
    # ──────────────────────────────────────────────────────────────

    async def cancel_order(
        self,
        order_id: str = "",
        reason: str = "",
        cancelled_by: str = "",
        refund_requested: bool = False,
        **kwargs
    ) -> Dict[str, Any]:
        """Cancel an order with reason tracking."""
        if not order_id:
            return {"success": False, "error": "Order ID is required"}
        if not reason:
            return {"success": False, "error": "Cancellation reason is required"}

        now = datetime.now()

        cancellation = {
            "order_id": order_id,
            "status": "cancelled",
            "reason": reason,
            "cancelled_by": cancelled_by or "customer",
            "cancelled_at": now.isoformat(),
            "refund_requested": refund_requested,
        }

        refund_text = " (refund requested)" if refund_requested else ""

        return {
            "success": True,
            "cancellation": cancellation,
            "order_id": order_id,
            "message": f"❌ Order {order_id} cancelled — Reason: {reason}{refund_text}",
        }

    # ──────────────────────────────────────────────────────────────
    # 7. CALCULATE ORDER TOTAL
    # ──────────────────────────────────────────────────────────────

    async def calculate_order_total(
        self,
        items: List[Dict[str, Any]] = None,
        tax_rate: float = 0.0,
        discount: float = 0.0,
        discount_type: str = "percentage",
        delivery_fee: float = 0.0,
        currency: str = "KES",
        **kwargs
    ) -> Dict[str, Any]:
        """
        Calculate order totals with tax, discounts, and delivery fees.

        discount_type: "percentage" (0-100) or "fixed" (absolute amount)
        """
        if not items or len(items) == 0:
            return {"success": False, "error": "Items are required to calculate total"}

        # Calculate subtotal
        subtotal = 0.0
        item_breakdown = []
        for i, item in enumerate(items):
            quantity = float(item.get("quantity", 1))
            unit_price = float(item.get("unit_price", 0))
            item_total = quantity * unit_price
            subtotal += item_total
            item_breakdown.append({
                "name": item.get("name", f"Item {i + 1}"),
                "quantity": quantity,
                "unit_price": unit_price,
                "total": round(item_total, 2),
            })

        # Calculate discount
        if discount_type == "percentage":
            discount_amount = subtotal * (min(discount, 100) / 100)
        else:
            discount_amount = min(discount, subtotal)

        after_discount = subtotal - discount_amount

        # Calculate tax
        tax_amount = after_discount * (tax_rate / 100) if tax_rate > 0 else 0.0

        # Grand total
        grand_total = after_discount + tax_amount + delivery_fee

        return {
            "success": True,
            "breakdown": {
                "items": item_breakdown,
                "subtotal": round(subtotal, 2),
                "discount": round(discount_amount, 2),
                "discount_description": f"{discount}%" if discount_type == "percentage" else f"{currency} {discount:,.2f}",
                "after_discount": round(after_discount, 2),
                "tax_rate": tax_rate,
                "tax_amount": round(tax_amount, 2),
                "delivery_fee": round(delivery_fee, 2),
                "grand_total": round(grand_total, 2),
                "currency": currency,
            },
            "grand_total": round(grand_total, 2),
            "currency": currency,
            "message": f"💰 Order total: {currency} {grand_total:,.2f} (subtotal: {subtotal:,.2f}, tax: {tax_amount:,.2f}, delivery: {delivery_fee:,.2f})",
        }

    # ──────────────────────────────────────────────────────────────
    # 8. FORMAT ORDER RECEIPT
    # ──────────────────────────────────────────────────────────────

    async def format_order_receipt(
        self,
        order_data: Dict[str, Any] = None,
        format_type: str = "whatsapp",
        business_name: str = "",
        business_phone: str = "",
        currency: str = "KES",
        **kwargs
    ) -> Dict[str, Any]:
        """Format a customer-facing order receipt for WhatsApp/SMS."""
        if not order_data:
            return {"success": False, "error": "Order data is required"}

        order_id = order_data.get("order_id", "N/A")
        customer = order_data.get("customer", {})
        items = order_data.get("items", [])
        status = order_data.get("status", "pending")
        subtotal = order_data.get("subtotal", 0)
        currency = order_data.get("currency", currency)
        now = datetime.now()

        # Build items list
        items_text = ""
        for item in items:
            name = item.get("name", "Item")
            qty = item.get("quantity", 1)
            unit = item.get("unit", "pcs")
            price = item.get("total", item.get("unit_price", 0))

            variant_info = ""
            if item.get("size"):
                variant_info += f" ({item['size']}"
                if item.get("color"):
                    variant_info += f", {item['color']}"
                variant_info += ")"
            elif item.get("color"):
                variant_info += f" ({item['color']})"
            elif item.get("cut"):
                variant_info += f" ({item['cut']})"

            items_text += f"\n  • {name}{variant_info} × {qty} {unit} — {currency} {price:,.0f}"

        business_header = f"\n🏪 *{business_name}*\n" if business_name else ""
        business_footer = f"\n📞 {business_phone}" if business_phone else ""

        delivery_text = ""
        if order_data.get("delivery_method"):
            method = order_data["delivery_method"].replace("_", " ").title()
            delivery_text = f"\n🚚 *Delivery:* {method}"
            if order_data.get("delivery_address"):
                delivery_text += f"\n📍 *Address:* {order_data['delivery_address']}"

        status_icon = {
            "pending": "🕐", "confirmed": "✅", "preparing": "👨‍🍳",
            "ready": "📦", "shipped": "🚚", "delivered": "✅",
            "cancelled": "❌", "refunded": "💰",
        }.get(status, "📋")

        if format_type == "whatsapp":
            message = (
                f"🧾 *ORDER RECEIPT*\n"
                f"━━━━━━━━━━━━━━━━━━━━{business_header}\n"
                f"📋 Order: *{order_id}*\n"
                f"👤 Customer: *{customer.get('name', 'N/A')}*\n"
                f"{status_icon} Status: *{status.replace('_', ' ').title()}*\n"
                f"📅 Date: {now.strftime('%d %b %Y, %I:%M %p')}\n\n"
                f"📝 *Items:*{items_text}\n\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"💰 *Total: {currency} {subtotal:,.0f}*"
                f"{delivery_text}"
                f"{business_footer}\n\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"_Thank you for your order!_ 🙏"
            )
        elif format_type == "sms":
            items_short = ", ".join(
                f"{item.get('name', 'Item')} x{item.get('quantity', 1)}" for item in items[:5]
            )
            message = (
                f"Order {order_id} received! "
                f"Items: {items_short}. "
                f"Total: {currency} {subtotal:,.0f}. "
                f"Status: {status.title()}."
            )
        else:
            # Plain text
            items_plain = "\n".join(
                f"  - {item.get('name', 'Item')} x{item.get('quantity', 1)} = {currency} {item.get('total', 0):,.0f}"
                for item in items
            )
            message = (
                f"ORDER RECEIPT\n"
                f"Order: {order_id}\n"
                f"Customer: {customer.get('name', 'N/A')}\n"
                f"Status: {status.title()}\n"
                f"Items:\n{items_plain}\n"
                f"Total: {currency} {subtotal:,.0f}"
            )

        return {
            "success": True,
            "message": message,
            "format_type": format_type,
            "order_id": order_id,
        }

    # ──────────────────────────────────────────────────────────────
    # 9. FORMAT ORDER NOTIFICATION
    # ──────────────────────────────────────────────────────────────

    async def format_order_notification(
        self,
        order_data: Dict[str, Any] = None,
        notification_type: str = "new_order",
        recipient_name: str = "Team",
        **kwargs
    ) -> Dict[str, Any]:
        """
        Format a merchant/kitchen/warehouse notification.
        notification_type: new_order, status_change, cancellation
        """
        if not order_data:
            return {"success": False, "error": "Order data is required"}

        order_id = order_data.get("order_id", "N/A")
        customer = order_data.get("customer", {})
        items = order_data.get("items", [])
        currency = order_data.get("currency", "KES")
        now = datetime.now()

        items_text = ""
        for item in items:
            name = item.get("name", "Item")
            qty = item.get("quantity", 1)
            unit = item.get("unit", "pcs")
            notes = item.get("notes", "")

            item_line = f"\n  ▸ {qty} {unit} — {name}"
            if notes:
                item_line += f" ⚠️ _{notes}_"
            items_text += item_line

        if notification_type == "new_order":
            order_type = order_data.get("order_type", "").title()
            delivery = order_data.get("delivery_method", "").replace("_", " ").title()

            message = (
                f"🔔 *NEW ORDER ALERT*\n"
                f"━━━━━━━━━━━━━━━━━━━━\n\n"
                f"📋 *{order_id}* | {order_type}\n"
                f"👤 {customer.get('name', 'N/A')} — {customer.get('phone', 'N/A')}\n"
                f"🚚 {delivery}\n\n"
                f"📝 *Items:*{items_text}\n\n"
                f"💰 Total: *{currency} {order_data.get('subtotal', 0):,.0f}*\n"
                f"🕐 {now.strftime('%I:%M %p')}\n\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"_Reply ✅ to confirm or ❌ to decline_"
            )

        elif notification_type == "status_change":
            new_status = order_data.get("status", "unknown").replace("_", " ").title()
            message = (
                f"📊 *ORDER STATUS UPDATE*\n\n"
                f"📋 Order: *{order_id}*\n"
                f"👤 Customer: {customer.get('name', 'N/A')}\n"
                f"📊 New Status: *{new_status}*\n"
                f"🕐 Updated: {now.strftime('%d %b %Y, %I:%M %p')}"
            )

        elif notification_type == "cancellation":
            reason = order_data.get("cancellation_reason", "Not specified")
            message = (
                f"❌ *ORDER CANCELLED*\n\n"
                f"📋 Order: *{order_id}*\n"
                f"👤 Customer: {customer.get('name', 'N/A')}\n"
                f"📝 Reason: {reason}\n"
                f"🕐 {now.strftime('%d %b %Y, %I:%M %p')}\n\n"
                f"_Please update inventory accordingly._"
            )

        else:
            message = (
                f"📋 *Order {order_id}* — Notification\n"
                f"Type: {notification_type}\n"
                f"Customer: {customer.get('name', 'N/A')}"
            )

        return {
            "success": True,
            "message": message,
            "notification_type": notification_type,
            "order_id": order_id,
            "recipient": recipient_name,
        }


# Global instance
order_service = OrderService()
