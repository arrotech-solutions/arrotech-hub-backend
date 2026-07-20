"""
Rent & Utility Collection Service for Arrotech Hub.

Stateless processing tools for property rent and utility payment collection.
No database models — data flows through workflow variables + external storage
(Google Sheets / Airtable).

Designed for Kenyan property managers (WhatsApp + M-Pesa focused).
Supports: rent, water, electricity, garbage collection billing.

Operations:
    generate_consolidated_invoice  — Combined rent + utilities invoice
    format_utility_reminder        — WhatsApp-friendly utility payment reminder
    process_partial_payment        — Record partial payment, calculate balance
    generate_tenant_statement      — Full statement for a period
    calculate_utility_charges      — Calculate utility bills from rates/readings
    format_payment_confirmation    — Confirm payment receipt per utility type
    classify_tenant_intent         — Detect tenant intent from WhatsApp message
    generate_collection_summary    — Landlord-facing collection report
    format_overdue_notice          — Escalating overdue notices
    format_utility_bill_breakdown  — Itemized bill breakdown
    lookup_tenant                  — Look up tenant by phone from data source
    register_tenant                — Auto-register new tenant on first contact
"""

import logging
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class RentCollectionService:
    """Stateless rent & utility collection tools for workflow building blocks."""

    def __init__(self):
        # Tenant intent keywords in English and Swahili
        self.TENANT_INTENT_KEYWORDS = {
            "pay_rent": [
                "pay rent", "rent payment", "lipa kodi", "kulipa kodi",
                "pay my rent", "rent", "kodi",
            ],
            "pay_water": [
                "pay water", "water bill", "maji", "lipa maji",
                "water payment", "pay for water",
            ],
            "pay_electricity": [
                "pay electricity", "electricity bill", "stima", "lipa stima",
                "power bill", "pay power", "umeme", "lipa umeme",
            ],
            "pay_garbage": [
                "pay garbage", "garbage collection", "takataka", "lipa takataka",
                "waste collection", "trash", "refuse",
            ],
            "pay_all": [
                "pay everything", "pay all", "lipa yote", "total bill",
                "full payment", "pay balance", "lipa balance",
            ],
            "check_balance": [
                "balance", "how much", "owe", "statement", "bill",
                "salio", "deni", "kiasi", "nadaiwa", "unadaiwa",
                "what do i owe", "how much do i owe",
            ],
            "payment_confirm": [
                "i have paid", "nimelipa", "nimeshalipa", "sent payment",
                "paid already", "check payment", "confirm payment",
            ],
            "maintenance": [
                "broken", "leak", "repair", "fix", "maintenance",
                "plumbing", "electrical", "haribika", "vunja",
            ],
            "complaint": [
                "complain", "complaint", "problem", "issue", "not fair",
                "malalamiko", "tatizo", "shida",
            ],
            "greeting": [
                "hello", "hi", "hey", "habari", "hujambo", "mambo",
                "good morning", "good afternoon", "good evening",
                "sasa", "niaje", "vipi",
            ],
        }

        # M-Pesa confirmation message pattern
        self.MPESA_PATTERN = re.compile(
            r'([A-Z0-9]{10})\s+Confirmed.*?Ksh([\d,]+\.?\d*)\s+'
            r'.*?on\s+(\d{1,2}/\d{1,2}/\d{2,4})',
            re.IGNORECASE | re.DOTALL,
        )

    async def handle_operation(
        self,
        operation: str,
        **kwargs,
    ) -> Dict[str, Any]:
        """Route to the appropriate rent collection tool."""
        try:
            kwargs = self._coerce_types(kwargs)

            operations_map = {
                "generate_consolidated_invoice": self.generate_consolidated_invoice,
                "format_utility_reminder": self.format_utility_reminder,
                "process_partial_payment": self.process_partial_payment,
                "generate_tenant_statement": self.generate_tenant_statement,
                "calculate_utility_charges": self.calculate_utility_charges,
                "format_payment_confirmation": self.format_payment_confirmation,
                "classify_tenant_intent": self.classify_tenant_intent,
                "generate_collection_summary": self.generate_collection_summary,
                "format_overdue_notice": self.format_overdue_notice,
                "format_utility_bill_breakdown": self.format_utility_bill_breakdown,
                "lookup_tenant": self.lookup_tenant,
                "register_tenant": self.register_tenant,
            }

            handler = operations_map.get(operation)
            if not handler:
                return {"success": False, "error": f"Unknown operation: {operation}"}

            return await handler(**kwargs)

        except Exception as e:
            logger.error(f"Rent collection tool error ({operation}): {e}")
            return {"success": False, "error": str(e)}

    # ──────────────────────────────────────────────────────────────
    # TYPE COERCION
    # ──────────────────────────────────────────────────────────────

    @staticmethod
    def _coerce_types(kwargs: Dict[str, Any]) -> Dict[str, Any]:
        """Coerce string values from workflow variables to proper types."""
        float_fields = {
            "amount", "rent_amount", "water_amount", "electricity_amount",
            "garbage_amount", "total_amount", "balance", "paid_amount",
            "monthly_rent", "water_flat_rate", "garbage_monthly_fee",
            "electricity_rate", "meter_reading_current", "meter_reading_previous",
            "total_expected", "total_collected", "total_outstanding",
        }
        int_fields = {
            "total_units", "occupied_units", "rent_due_day",
            "total_tenants", "paid_count", "unpaid_count",
        }
        bool_fields = {
            "water_billing_enabled", "electricity_billing_enabled",
            "garbage_billing_enabled",
        }

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
            elif key in bool_fields and isinstance(value, str):
                coerced[key] = value.lower() in ("true", "1", "yes")
            else:
                coerced[key] = value

        return coerced

    # ──────────────────────────────────────────────────────────────
    # LANGUAGE HELPERS
    # ──────────────────────────────────────────────────────────────

    @staticmethod
    def _detect_language(message: str) -> str:
        """Detect if a message is in Swahili or English."""
        swahili_markers = [
            "habari", "hujambo", "mambo", "sasa", "niaje", "vipi",
            "nataka", "naomba", "tafadhali", "asante", "karibu",
            "nyumba", "maji", "stima", "kodi", "takataka",
            "lipa", "kulipa", "nimelipa", "nimeshalipa",
            "kiasi", "salio", "deni", "nadaiwa",
            "ndiyo", "hapana", "sawa", "poa",
        ]
        msg_lower = message.lower()
        swahili_count = sum(1 for w in swahili_markers if w in msg_lower)
        return "sw" if swahili_count >= 2 else "en"

    @staticmethod
    def _fmt_amount(amount: float, currency: str = "KES") -> str:
        """Format currency amount."""
        return f"{currency} {amount:,.0f}"

    # ──────────────────────────────────────────────────────────────
    # 1. GENERATE CONSOLIDATED INVOICE
    # ──────────────────────────────────────────────────────────────

    async def generate_consolidated_invoice(
        self,
        tenant_name: str = "Tenant",
        unit: str = "",
        property_name: str = "",
        period: str = "",
        rent_amount: float = 0,
        water_amount: float = 0,
        electricity_amount: float = 0,
        garbage_amount: float = 0,
        water_billing_enabled: bool = True,
        electricity_billing_enabled: bool = True,
        garbage_billing_enabled: bool = True,
        paybill_number: str = "",
        account_number: str = "",
        currency: str = "KES",
        language: str = "en",
        previous_balance: float = 0,
        **kwargs,
    ) -> Dict[str, Any]:
        """Generate a consolidated invoice combining rent + all utilities."""
        if not rent_amount and not any([water_amount, electricity_amount, garbage_amount]):
            return {"success": False, "error": "At least one charge amount is required"}

        if not period:
            period = datetime.now().strftime("%B %Y")

        if not account_number and unit:
            account_number = f"{unit}-{datetime.now().strftime('%b%Y').upper()}"

        # Build line items
        lines = []
        total = 0.0

        if rent_amount > 0:
            lines.append(("🏠", "Rent" if language == "en" else "Kodi", rent_amount))
            total += rent_amount

        if water_billing_enabled and water_amount > 0:
            lines.append(("💧", "Water" if language == "en" else "Maji", water_amount))
            total += water_amount

        if electricity_billing_enabled and electricity_amount > 0:
            lines.append(("⚡", "Electricity" if language == "en" else "Stima", electricity_amount))
            total += electricity_amount

        if garbage_billing_enabled and garbage_amount > 0:
            lines.append(("🗑️", "Garbage" if language == "en" else "Takataka", garbage_amount))
            total += garbage_amount

        grand_total = total + previous_balance

        # Format invoice
        unit_info = f" — Unit {unit}" if unit else ""
        property_info = f"\n🏢 {property_name}" if property_name else ""

        lines_text = ""
        for icon, label, amt in lines:
            lines_text += f"\n{icon} {label}:{' ' * (16 - len(label))}{self._fmt_amount(amt, currency)}"

        balance_text = ""
        if previous_balance > 0:
            bal_label = "Previous Balance" if language == "en" else "Salio la Awali"
            balance_text = f"\n⚠️ {bal_label}:{' ' * max(1, 16 - len(bal_label))}{self._fmt_amount(previous_balance, currency)}"

        # Payment info
        payment_info = ""
        if paybill_number:
            pay_label = "Pay via M-Pesa" if language == "en" else "Lipa kupitia M-Pesa"
            payment_info = (
                f"\n\n💳 *{pay_label}:*\n"
                f"  • Paybill: {paybill_number}\n"
                f"  • Account: {account_number}\n"
                f"  • Amount: {self._fmt_amount(grand_total, currency)}"
            )

        if language == "sw":
            header = "ANKARA YA MWEZI"
            period_label = "Kipindi"
            total_label = "Jumla"
            pay_prompt = "Jibu 'LIPA' kulipa sasa kupitia M-Pesa"
        else:
            header = "MONTHLY INVOICE"
            period_label = "Period"
            total_label = "Total Due"
            pay_prompt = "Reply 'PAY' to pay now via M-Pesa"

        invoice_no = f"INV-{datetime.now().strftime('%Y%m%d%H%M')}"

        message = (
            f"📋 *{header}*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 *{tenant_name}*{unit_info}{property_info}\n"
            f"📅 {period_label}: *{period}*\n"
            f"📋 Invoice: {invoice_no}\n"
            f"\n📝 *Charges:*{lines_text}"
            f"{balance_text}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 *{total_label}: {self._fmt_amount(grand_total, currency)}*"
            f"{payment_info}\n\n"
            f"_{pay_prompt}_ 📲"
        )

        return {
            "success": True,
            "message": message,
            "invoice_number": invoice_no,
            "rent_amount": rent_amount,
            "water_amount": water_amount,
            "electricity_amount": electricity_amount,
            "garbage_amount": garbage_amount,
            "previous_balance": previous_balance,
            "subtotal": total,
            "grand_total": grand_total,
            "currency": currency,
            "period": period,
            "tenant_name": tenant_name,
            "unit": unit,
            "account_number": account_number,
        }

    # ──────────────────────────────────────────────────────────────
    # 2. FORMAT UTILITY REMINDER
    # ──────────────────────────────────────────────────────────────

    async def format_utility_reminder(
        self,
        tenant_name: str = "Tenant",
        utility_type: str = "water",
        amount: float = 0,
        due_date: str = "",
        unit: str = "",
        property_name: str = "",
        paybill_number: str = "",
        account_number: str = "",
        currency: str = "KES",
        language: str = "en",
        **kwargs,
    ) -> Dict[str, Any]:
        """Format a WhatsApp-friendly utility payment reminder."""
        if not amount:
            return {"success": False, "error": "Amount is required"}

        if not due_date:
            due_date = datetime.now().strftime("%d/%m/%Y")

        icons = {
            "water": "💧", "electricity": "⚡", "garbage": "🗑️",
            "rent": "🏠", "all": "📋",
        }
        labels_en = {
            "water": "Water Bill", "electricity": "Electricity Bill",
            "garbage": "Garbage Collection", "rent": "Rent",
            "all": "Monthly Charges",
        }
        labels_sw = {
            "water": "Bili ya Maji", "electricity": "Bili ya Stima",
            "garbage": "Ushuru wa Takataka", "rent": "Kodi",
            "all": "Malipo ya Mwezi",
        }

        icon = icons.get(utility_type, "📋")
        label = (labels_sw if language == "sw" else labels_en).get(utility_type, utility_type.title())

        amount_fmt = self._fmt_amount(amount, currency)
        unit_info = f" for *{unit}*" if unit else ""

        payment_info = ""
        if paybill_number:
            payment_info = (
                f"\n\n💳 *{'Lipa kupitia M-Pesa' if language == 'sw' else 'Pay via M-Pesa'}:*\n"
                f"  • Paybill: {paybill_number}\n"
                f"  • Account: {account_number or unit}\n"
                f"  • Amount: {amount_fmt}"
            )

        if language == "sw":
            message = (
                f"{icon} *Ukumbusho: {label}*\n\n"
                f"Habari *{tenant_name}*,\n\n"
                f"{label} yako ya *{amount_fmt}*{unit_info} inatakiwa kulipwa "
                f"ifikapo *{due_date}*.\n\n"
                f"Tafadhali lipa kwa wakati ili kuepuka usumbufu.{payment_info}\n\n"
                f"Asante! 🙏"
            )
        else:
            message = (
                f"{icon} *Reminder: {label}*\n\n"
                f"Dear *{tenant_name}*,\n\n"
                f"Your {label.lower()} of *{amount_fmt}*{unit_info} is due "
                f"on *{due_date}*.\n\n"
                f"Please make your payment on time to avoid any inconvenience.{payment_info}\n\n"
                f"Thank you! 🙏"
            )

        return {
            "success": True,
            "message": message,
            "utility_type": utility_type,
            "formatted_amount": amount_fmt,
            "tenant_name": tenant_name,
            "due_date": due_date,
        }

    # ──────────────────────────────────────────────────────────────
    # 3. PROCESS PARTIAL PAYMENT
    # ──────────────────────────────────────────────────────────────

    async def process_partial_payment(
        self,
        tenant_name: str = "Tenant",
        unit: str = "",
        total_amount: float = 0,
        paid_amount: float = 0,
        payment_method: str = "M-Pesa",
        transaction_id: str = "",
        period: str = "",
        currency: str = "KES",
        language: str = "en",
        **kwargs,
    ) -> Dict[str, Any]:
        """Record a partial payment, calculate remaining balance."""
        if not paid_amount:
            return {"success": False, "error": "Paid amount is required"}

        if not period:
            period = datetime.now().strftime("%B %Y")

        balance = max(0, total_amount - paid_amount)
        is_fully_paid = balance <= 0

        now = datetime.now()
        receipt_no = f"RCP-{now.strftime('%Y%m%d%H%M%S')}"

        paid_fmt = self._fmt_amount(paid_amount, currency)
        balance_fmt = self._fmt_amount(balance, currency)
        total_fmt = self._fmt_amount(total_amount, currency)

        tx_info = f"\n🆔 Transaction: {transaction_id}" if transaction_id else ""

        if is_fully_paid:
            if language == "sw":
                status_text = "\n\n✅ *Umelipa Kikamilifu* — Hakuna salio"
            else:
                status_text = "\n\n✅ *Fully Paid* — No outstanding balance"
        else:
            if language == "sw":
                status_text = f"\n\n⚠️ *Salio Lililobaki: {balance_fmt}*"
            else:
                status_text = f"\n\n⚠️ *Remaining Balance: {balance_fmt}*"

        unit_info = f"\n📍 Unit: {unit}" if unit else ""

        if language == "sw":
            message = (
                f"✅ *MALIPO YAMEPOKEWA*\n"
                f"━━━━━━━━━━━━━━━━━━━━\n\n"
                f"📋 Risiti: *{receipt_no}*\n"
                f"👤 Mpangaji: *{tenant_name}*{unit_info}\n"
                f"📅 Kipindi: *{period}*\n\n"
                f"💰 Kiasi Kilicholipwa: *{paid_fmt}*\n"
                f"💳 Njia: {payment_method}{tx_info}\n"
                f"🕐 Tarehe: {now.strftime('%d %b %Y, %I:%M %p')}\n\n"
                f"📊 Jumla ya Bili: {total_fmt}"
                f"{status_text}\n\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"_Asante kwa malipo yako!_ 🙏"
            )
        else:
            message = (
                f"✅ *PAYMENT RECEIVED*\n"
                f"━━━━━━━━━━━━━━━━━━━━\n\n"
                f"📋 Receipt: *{receipt_no}*\n"
                f"👤 Tenant: *{tenant_name}*{unit_info}\n"
                f"📅 Period: *{period}*\n\n"
                f"💰 Amount Paid: *{paid_fmt}*\n"
                f"💳 Method: {payment_method}{tx_info}\n"
                f"🕐 Date: {now.strftime('%d %b %Y, %I:%M %p')}\n\n"
                f"📊 Total Bill: {total_fmt}"
                f"{status_text}\n\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"_Thank you for your payment!_ 🙏"
            )

        return {
            "success": True,
            "message": message,
            "receipt_number": receipt_no,
            "paid_amount": paid_amount,
            "total_amount": total_amount,
            "balance": balance,
            "is_fully_paid": is_fully_paid,
            "period": period,
            "transaction_id": transaction_id,
            "tenant_name": tenant_name,
            "unit": unit,
        }

    # ──────────────────────────────────────────────────────────────
    # 4. GENERATE TENANT STATEMENT
    # ──────────────────────────────────────────────────────────────

    async def generate_tenant_statement(
        self,
        tenant_name: str = "Tenant",
        unit: str = "",
        property_name: str = "",
        period: str = "",
        rent_amount: float = 0,
        water_amount: float = 0,
        electricity_amount: float = 0,
        garbage_amount: float = 0,
        payments: Optional[List[Dict[str, Any]]] = None,
        currency: str = "KES",
        language: str = "en",
        **kwargs,
    ) -> Dict[str, Any]:
        """Generate a full statement showing rent + all utilities for a period."""
        if not period:
            period = datetime.now().strftime("%B %Y")

        if not payments:
            payments = []

        total_charges = rent_amount + water_amount + electricity_amount + garbage_amount
        total_paid = sum(p.get("amount", 0) for p in payments)
        balance = total_charges - total_paid

        # Charges breakdown
        charges_text = ""
        if rent_amount > 0:
            charges_text += f"\n  🏠 {'Kodi' if language == 'sw' else 'Rent'}: {self._fmt_amount(rent_amount, currency)}"
        if water_amount > 0:
            charges_text += f"\n  💧 {'Maji' if language == 'sw' else 'Water'}: {self._fmt_amount(water_amount, currency)}"
        if electricity_amount > 0:
            charges_text += f"\n  ⚡ {'Stima' if language == 'sw' else 'Electricity'}: {self._fmt_amount(electricity_amount, currency)}"
        if garbage_amount > 0:
            charges_text += f"\n  🗑️ {'Takataka' if language == 'sw' else 'Garbage'}: {self._fmt_amount(garbage_amount, currency)}"

        if not charges_text:
            charges_text = "\n  — No charges"

        # Payments list
        payments_text = ""
        if payments:
            for p in payments:
                date = p.get("date", "N/A")
                amt = p.get("amount", 0)
                method = p.get("method", "M-Pesa")
                ref = p.get("reference", "")
                ref_text = f" [{ref}]" if ref else ""
                payments_text += f"\n  ✅ {date} — {self._fmt_amount(amt, currency)} ({method}){ref_text}"
        else:
            if language == "sw":
                payments_text = "\n  ❌ Hakuna malipo yaliyorekodiwa"
            else:
                payments_text = "\n  ❌ No payments recorded"

        unit_text = f" — Unit {unit}" if unit else ""
        property_text = f"\n🏢 {property_name}" if property_name else ""

        status_icon = "✅" if balance <= 0 else "⚠️"
        if balance <= 0:
            status_text = "PAID" if language == "en" else "UMELIPA"
        else:
            bal_label = "BALANCE DUE" if language == "en" else "SALIO"
            status_text = f"{bal_label}: {self._fmt_amount(balance, currency)}"

        header = "TAARIFA YA MPANGAJI" if language == "sw" else "TENANT STATEMENT"
        charges_label = "Malipo Yanayotakiwa" if language == "sw" else "Charges"
        payments_label = "Malipo Yaliyofanywa" if language == "sw" else "Payments"
        total_label = "Jumla ya Malipo" if language == "sw" else "Total Charges"
        paid_label = "Jumla Iliyolipwa" if language == "sw" else "Total Paid"

        message = (
            f"📊 *{header}*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 *{tenant_name}*{unit_text}{property_text}\n"
            f"📅 {'Kipindi' if language == 'sw' else 'Period'}: *{period}*\n\n"
            f"📝 *{charges_label}:*{charges_text}\n\n"
            f"💳 *{payments_label}:*{payments_text}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 {total_label}: {self._fmt_amount(total_charges, currency)}\n"
            f"💵 {paid_label}: {self._fmt_amount(total_paid, currency)}\n"
            f"{status_icon} Status: *{status_text}*\n"
            f"━━━━━━━━━━━━━━━━━━━━"
        )

        return {
            "success": True,
            "message": message,
            "total_charges": total_charges,
            "total_paid": total_paid,
            "balance": balance,
            "is_fully_paid": balance <= 0,
            "payment_count": len(payments),
            "period": period,
        }

    # ──────────────────────────────────────────────────────────────
    # 5. CALCULATE UTILITY CHARGES
    # ──────────────────────────────────────────────────────────────

    async def calculate_utility_charges(
        self,
        utility_type: str = "water",
        meter_reading_current: float = 0,
        meter_reading_previous: float = 0,
        rate_per_unit: float = 0,
        flat_rate: float = 0,
        currency: str = "KES",
        **kwargs,
    ) -> Dict[str, Any]:
        """Calculate utility bills from meter readings or flat rates."""
        if flat_rate > 0:
            amount = flat_rate
            units_consumed = 0
            calculation_method = "flat_rate"
        elif rate_per_unit > 0 and meter_reading_current > 0:
            units_consumed = max(0, meter_reading_current - meter_reading_previous)
            amount = units_consumed * rate_per_unit
            calculation_method = "metered"
        else:
            return {
                "success": False,
                "error": "Either flat_rate or (rate_per_unit + meter readings) is required",
            }

        unit_labels = {
            "water": "cubic meters",
            "electricity": "kWh",
        }

        return {
            "success": True,
            "utility_type": utility_type,
            "amount": round(amount, 2),
            "formatted_amount": self._fmt_amount(amount, currency),
            "units_consumed": units_consumed,
            "unit_label": unit_labels.get(utility_type, "units"),
            "calculation_method": calculation_method,
            "meter_reading_current": meter_reading_current,
            "meter_reading_previous": meter_reading_previous,
            "rate_per_unit": rate_per_unit,
            "flat_rate": flat_rate,
            "message": (
                f"Calculated {utility_type} charge: "
                f"{self._fmt_amount(amount, currency)}"
                + (f" ({units_consumed} {unit_labels.get(utility_type, 'units')} × "
                   f"{self._fmt_amount(rate_per_unit, currency)})"
                   if calculation_method == "metered" else " (flat rate)")
            ),
        }

    # ──────────────────────────────────────────────────────────────
    # 6. FORMAT PAYMENT CONFIRMATION
    # ──────────────────────────────────────────────────────────────

    async def format_payment_confirmation(
        self,
        tenant_name: str = "Tenant",
        amount: float = 0,
        payment_type: str = "rent",
        payment_method: str = "M-Pesa",
        transaction_id: str = "",
        unit: str = "",
        property_name: str = "",
        balance: float = 0,
        currency: str = "KES",
        language: str = "en",
        **kwargs,
    ) -> Dict[str, Any]:
        """Confirm payment receipt for a specific utility type."""
        if not amount:
            return {"success": False, "error": "Amount is required"}

        now = datetime.now()
        receipt_no = f"RCP-{now.strftime('%Y%m%d%H%M%S')}"

        type_icons = {
            "rent": "🏠", "water": "💧", "electricity": "⚡",
            "garbage": "🗑️", "all": "📋",
        }
        type_labels_en = {
            "rent": "Rent", "water": "Water", "electricity": "Electricity",
            "garbage": "Garbage", "all": "Monthly Charges",
        }
        type_labels_sw = {
            "rent": "Kodi", "water": "Maji", "electricity": "Stima",
            "garbage": "Takataka", "all": "Malipo ya Mwezi",
        }

        icon = type_icons.get(payment_type, "📋")
        label = (type_labels_sw if language == "sw" else type_labels_en).get(
            payment_type, payment_type.title()
        )

        amount_fmt = self._fmt_amount(amount, currency)
        tx_info = f"\n🆔 Transaction: {transaction_id}" if transaction_id else ""
        unit_info = f"\n📍 Unit: {unit}" if unit else ""

        balance_info = ""
        if balance > 0:
            if language == "sw":
                balance_info = f"\n\n⚠️ *Salio Lililobaki: {self._fmt_amount(balance, currency)}*"
            else:
                balance_info = f"\n\n⚠️ *Outstanding Balance: {self._fmt_amount(balance, currency)}*"
        elif balance == 0:
            if language == "sw":
                balance_info = "\n\n✅ *Umelipa Kikamilifu* — Hakuna salio"
            else:
                balance_info = "\n\n✅ *Fully Paid* — No outstanding balance"

        if language == "sw":
            message = (
                f"{icon} *MALIPO YA {label.upper()} YAMEPOKEWA*\n"
                f"━━━━━━━━━━━━━━━━━━━━\n\n"
                f"📋 Risiti: *{receipt_no}*\n"
                f"👤 Mpangaji: *{tenant_name}*{unit_info}\n\n"
                f"💰 Kiasi: *{amount_fmt}*\n"
                f"💳 Njia: {payment_method}{tx_info}\n"
                f"🕐 Tarehe: {now.strftime('%d %b %Y, %I:%M %p')}"
                f"{balance_info}\n\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"_Asante kwa malipo yako!_ 🙏"
            )
        else:
            message = (
                f"{icon} *{label.upper()} PAYMENT RECEIVED*\n"
                f"━━━━━━━━━━━━━━━━━━━━\n\n"
                f"📋 Receipt: *{receipt_no}*\n"
                f"👤 Tenant: *{tenant_name}*{unit_info}\n\n"
                f"💰 Amount: *{amount_fmt}*\n"
                f"💳 Method: {payment_method}{tx_info}\n"
                f"🕐 Date: {now.strftime('%d %b %Y, %I:%M %p')}"
                f"{balance_info}\n\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"_Thank you for your payment!_ 🙏"
            )

        return {
            "success": True,
            "message": message,
            "receipt_number": receipt_no,
            "formatted_amount": amount_fmt,
            "payment_type": payment_type,
            "has_balance": balance > 0,
        }

    # ──────────────────────────────────────────────────────────────
    # 7. CLASSIFY TENANT INTENT
    # ──────────────────────────────────────────────────────────────

    async def classify_tenant_intent(
        self,
        message: str = "",
        **kwargs,
    ) -> Dict[str, Any]:
        """Detect tenant intent from a WhatsApp message."""
        if not message:
            return {"success": False, "error": "Message text is required"}

        msg_lower = message.lower().strip()
        detected_intents = []

        # Check for M-Pesa confirmation
        mpesa_match = self.MPESA_PATTERN.search(message)
        if mpesa_match:
            return {
                "success": True,
                "primary_intent": "payment_confirm",
                "all_intents": ["payment_confirm"],
                "mpesa_transaction_id": mpesa_match.group(1),
                "mpesa_amount": float(mpesa_match.group(2).replace(",", "")),
                "mpesa_date": mpesa_match.group(3),
                "language": self._detect_language(message),
                "original_message": message,
                "message": "M-Pesa payment confirmation detected",
            }

        # Detect intents
        for intent, keywords in self.TENANT_INTENT_KEYWORDS.items():
            for kw in keywords:
                if kw in msg_lower:
                    detected_intents.append(intent)
                    break

        # Determine primary intent
        # Priority order: pay_all > pay_rent > pay_water > pay_electricity > pay_garbage
        # > check_balance > payment_confirm > maintenance > complaint > greeting
        priority = [
            "pay_all", "pay_rent", "pay_water", "pay_electricity",
            "pay_garbage", "check_balance", "payment_confirm",
            "maintenance", "complaint", "greeting",
        ]

        primary_intent = "general_inquiry"
        for p in priority:
            if p in detected_intents:
                primary_intent = p
                break

        # Urgency detection
        urgency = "normal"
        urgent_words = [
            "urgent", "asap", "immediately", "haraka", "sasa",
            "emergency", "please help", "tafadhali",
        ]
        if any(w in msg_lower for w in urgent_words):
            urgency = "high"

        language = self._detect_language(message)

        return {
            "success": True,
            "primary_intent": primary_intent,
            "all_intents": list(set(detected_intents)),
            "language": language,
            "urgency": urgency,
            "original_message": message,
            "message": f"Classified as '{primary_intent}' ({language})",
        }

    # ──────────────────────────────────────────────────────────────
    # 8. GENERATE COLLECTION SUMMARY
    # ──────────────────────────────────────────────────────────────

    async def generate_collection_summary(
        self,
        landlord_name: str = "Landlord",
        property_name: str = "Property",
        period: str = "",
        total_units: int = 0,
        occupied_units: int = 0,
        total_expected: float = 0,
        total_collected: float = 0,
        rent_collected: float = 0,
        water_collected: float = 0,
        electricity_collected: float = 0,
        garbage_collected: float = 0,
        paid_count: int = 0,
        unpaid_count: int = 0,
        unpaid_tenants: Optional[List[str]] = None,
        currency: str = "KES",
        **kwargs,
    ) -> Dict[str, Any]:
        """Generate landlord-facing collection report."""
        if not period:
            period = datetime.now().strftime("%B %Y")

        total_outstanding = max(0, total_expected - total_collected)
        collection_rate = (
            (total_collected / total_expected * 100) if total_expected > 0 else 0
        )
        occupancy_rate = (
            (occupied_units / total_units * 100) if total_units > 0 else 0
        )

        # Unpaid tenants list
        unpaid_text = ""
        if unpaid_tenants:
            unpaid_list = "\n".join(f"  • {t}" for t in unpaid_tenants[:15])
            unpaid_text = f"\n\n👥 *Unpaid Tenants:*\n{unpaid_list}"
            if len(unpaid_tenants) > 15:
                unpaid_text += f"\n  ... and {len(unpaid_tenants) - 15} more"

        # Collection breakdown
        breakdown_text = ""
        if any([rent_collected, water_collected, electricity_collected, garbage_collected]):
            breakdown_text = (
                f"\n\n📊 *Collection Breakdown:*\n"
                f"  🏠 Rent: {self._fmt_amount(rent_collected, currency)}\n"
                f"  💧 Water: {self._fmt_amount(water_collected, currency)}\n"
                f"  ⚡ Electricity: {self._fmt_amount(electricity_collected, currency)}\n"
                f"  🗑️ Garbage: {self._fmt_amount(garbage_collected, currency)}"
            )

        message = (
            f"📊 *COLLECTION REPORT*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 *{landlord_name}*\n"
            f"🏢 *{property_name}*\n"
            f"📅 *{period}*\n\n"
            f"🏠 *Occupancy:*\n"
            f"  • Units: {occupied_units}/{total_units} ({occupancy_rate:.0f}%)\n"
            f"  • Vacant: {total_units - occupied_units}\n\n"
            f"💰 *Collections:*\n"
            f"  • Expected: {self._fmt_amount(total_expected, currency)}\n"
            f"  • Collected: {self._fmt_amount(total_collected, currency)} ({collection_rate:.0f}%)\n"
            f"  • Outstanding: {self._fmt_amount(total_outstanding, currency)}\n\n"
            f"👥 *Tenants:*\n"
            f"  • Paid: {paid_count} ✅\n"
            f"  • Unpaid: {unpaid_count} ⚠️"
            f"{breakdown_text}"
            f"{unpaid_text}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━"
        )

        return {
            "success": True,
            "message": message,
            "total_expected": total_expected,
            "total_collected": total_collected,
            "total_outstanding": total_outstanding,
            "collection_rate": round(collection_rate, 1),
            "occupancy_rate": round(occupancy_rate, 1),
            "paid_count": paid_count,
            "unpaid_count": unpaid_count,
            "period": period,
        }

    # ──────────────────────────────────────────────────────────────
    # 9. FORMAT OVERDUE NOTICE
    # ──────────────────────────────────────────────────────────────

    async def format_overdue_notice(
        self,
        tenant_name: str = "Tenant",
        amount: float = 0,
        due_date: str = "",
        days_overdue: int = 0,
        unit: str = "",
        property_name: str = "",
        paybill_number: str = "",
        account_number: str = "",
        reminder_level: str = "first",
        landlord_name: str = "",
        currency: str = "KES",
        language: str = "en",
        **kwargs,
    ) -> Dict[str, Any]:
        """Format escalating overdue notices: friendly → warning → final."""
        if not amount:
            return {"success": False, "error": "Amount is required"}

        if not due_date:
            due_date = datetime.now().strftime("%d/%m/%Y")

        amount_fmt = self._fmt_amount(amount, currency)
        unit_info = f" for *{unit}*" if unit else ""
        property_info = f" at *{property_name}*" if property_name else ""
        sign_off = f"\n\n_{landlord_name or 'Property Management'}_"

        payment_info = ""
        if paybill_number:
            payment_info = (
                f"\n\n💳 *{'Maelezo ya Malipo' if language == 'sw' else 'Payment Details'}:*\n"
                f"  • Paybill: {paybill_number}\n"
                f"  • Account: {account_number or unit}\n"
                f"  • Amount: {amount_fmt}"
            )

        if language == "sw":
            messages = {
                "first": (
                    f"🏠 *Ukumbusho wa Malipo*\n\n"
                    f"Habari *{tenant_name}*,\n\n"
                    f"Malipo yako ya *{amount_fmt}*{unit_info}{property_info} "
                    f"yalipaswa kulipwa tarehe *{due_date}* na bado hayajalipwa.\n\n"
                    f"Tafadhali lipa haraka iwezekanavyo.{payment_info}\n\n"
                    f"Twasiliana nasi ukiwa na tatizo lolote.{sign_off}"
                ),
                "second": (
                    f"⚠️ *ONYO: Malipo Yamechelewa*\n\n"
                    f"*{tenant_name}*,\n\n"
                    f"Malipo yako ya *{amount_fmt}*{unit_info}{property_info} "
                    f"yamechelewa kwa siku *{days_overdue}*.\n\n"
                    f"Tarehe ya mwisho ilikuwa: *{due_date}*\n\n"
                    f"Tafadhali lipa SASA ili kuepuka adhabu.{payment_info}\n\n"
                    f"Twasiliana nasi mara moja.{sign_off}"
                ),
                "final": (
                    f"🚨 *NOTISI YA MWISHO*\n\n"
                    f"*{tenant_name}*,\n\n"
                    f"Hii ni *notisi ya mwisho* kuhusu deni lako la "
                    f"*{amount_fmt}*{unit_info}{property_info}.\n\n"
                    f"Tarehe ya mwisho ilikuwa: *{due_date}* (siku {days_overdue} zilizopita)\n\n"
                    f"Kushindwa kulipa ndani ya *masaa 48* kunaweza kusababisha "
                    f"hatua zaidi kwa mujibu wa mkataba wako.{payment_info}\n\n"
                    f"Tafadhali wasiliana nasi MARA MOJA kutatua suala hili.{sign_off}"
                ),
            }
        else:
            messages = {
                "first": (
                    f"🏠 *Payment Reminder*\n\n"
                    f"Dear *{tenant_name}*,\n\n"
                    f"Your payment of *{amount_fmt}*{unit_info}{property_info} "
                    f"was due on *{due_date}* and remains unpaid.\n\n"
                    f"Please make your payment as soon as possible.{payment_info}\n\n"
                    f"Contact us if you have any issues.{sign_off}"
                ),
                "second": (
                    f"⚠️ *WARNING: Payment Overdue*\n\n"
                    f"*{tenant_name}*,\n\n"
                    f"Your payment of *{amount_fmt}*{unit_info}{property_info} "
                    f"is now *{days_overdue} days overdue*.\n\n"
                    f"Original due date: *{due_date}*\n\n"
                    f"Please pay NOW to avoid penalties.{payment_info}\n\n"
                    f"Contact us immediately.{sign_off}"
                ),
                "final": (
                    f"🚨 *FINAL NOTICE*\n\n"
                    f"*{tenant_name}*,\n\n"
                    f"This is a *final notice* regarding your overdue payment of "
                    f"*{amount_fmt}*{unit_info}{property_info}.\n\n"
                    f"Original due date: *{due_date}* ({days_overdue} days ago)\n\n"
                    f"Failure to pay within *48 hours* may result in further action "
                    f"as per your lease agreement.{payment_info}\n\n"
                    f"Please contact us IMMEDIATELY to resolve this matter.{sign_off}"
                ),
            }

        message = messages.get(reminder_level, messages["first"])

        return {
            "success": True,
            "message": message,
            "reminder_level": reminder_level,
            "formatted_amount": amount_fmt,
            "days_overdue": days_overdue,
            "tenant_name": tenant_name,
            "is_final_notice": reminder_level == "final",
        }

    # ──────────────────────────────────────────────────────────────
    # 10. FORMAT UTILITY BILL BREAKDOWN
    # ──────────────────────────────────────────────────────────────

    async def format_utility_bill_breakdown(
        self,
        tenant_name: str = "Tenant",
        unit: str = "",
        property_name: str = "",
        period: str = "",
        rent_amount: float = 0,
        water_amount: float = 0,
        water_units: float = 0,
        water_rate: float = 0,
        electricity_amount: float = 0,
        electricity_units: float = 0,
        electricity_rate: float = 0,
        garbage_amount: float = 0,
        currency: str = "KES",
        language: str = "en",
        **kwargs,
    ) -> Dict[str, Any]:
        """Itemized bill breakdown: rent + water + electricity + garbage with calculations."""
        if not period:
            period = datetime.now().strftime("%B %Y")

        total = rent_amount + water_amount + electricity_amount + garbage_amount

        # Build breakdown
        lines = []
        if rent_amount > 0:
            lines.append(
                f"  🏠 {'Kodi' if language == 'sw' else 'Rent'}:\n"
                f"     {self._fmt_amount(rent_amount, currency)}"
            )

        if water_amount > 0:
            water_detail = ""
            if water_units > 0 and water_rate > 0:
                water_detail = f" ({water_units:.1f} m³ × {self._fmt_amount(water_rate, currency)}/m³)"
            lines.append(
                f"  💧 {'Maji' if language == 'sw' else 'Water'}:{water_detail}\n"
                f"     {self._fmt_amount(water_amount, currency)}"
            )

        if electricity_amount > 0:
            elec_detail = ""
            if electricity_units > 0 and electricity_rate > 0:
                elec_detail = f" ({electricity_units:.1f} kWh × {self._fmt_amount(electricity_rate, currency)}/kWh)"
            lines.append(
                f"  ⚡ {'Stima' if language == 'sw' else 'Electricity'}:{elec_detail}\n"
                f"     {self._fmt_amount(electricity_amount, currency)}"
            )

        if garbage_amount > 0:
            lines.append(
                f"  🗑️ {'Takataka' if language == 'sw' else 'Garbage Collection'}:\n"
                f"     {self._fmt_amount(garbage_amount, currency)}"
            )

        breakdown_text = "\n".join(lines) if lines else "  — No charges"

        unit_info = f" — Unit {unit}" if unit else ""
        property_text = f"\n🏢 {property_name}" if property_name else ""

        header = "MAELEZO YA BILI" if language == "sw" else "BILL BREAKDOWN"
        total_label = "JUMLA" if language == "sw" else "TOTAL"

        message = (
            f"📋 *{header}*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 *{tenant_name}*{unit_info}{property_text}\n"
            f"📅 {'Kipindi' if language == 'sw' else 'Period'}: *{period}*\n\n"
            f"{breakdown_text}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 *{total_label}: {self._fmt_amount(total, currency)}*\n"
            f"━━━━━━━━━━━━━━━━━━━━"
        )

        return {
            "success": True,
            "message": message,
            "rent_amount": rent_amount,
            "water_amount": water_amount,
            "electricity_amount": electricity_amount,
            "garbage_amount": garbage_amount,
            "total": total,
            "period": period,
        }

    # ──────────────────────────────────────────────────────────────
    # 11. LOOKUP TENANT
    # ──────────────────────────────────────────────────────────────

    async def lookup_tenant(
        self,
        phone_number: str = "",
        tenant_name: str = "",
        unit: str = "",
        tenants_data: Optional[List[Dict[str, Any]]] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Look up a tenant by phone number, name, or unit from configured data source.

        In v1, tenants_data is a list of dicts passed from workflow variables
        (loaded from Google Sheets / Airtable). Each dict should have:
        {name, phone, unit, rent_amount, water_amount, electricity_amount, garbage_amount, ...}
        """
        if not tenants_data:
            tenants_data = []

        if not phone_number and not tenant_name and not unit:
            return {"success": False, "error": "Phone number, name, or unit is required for lookup"}

        # Normalize phone for matching
        def _normalize_phone(p: str) -> str:
            cleaned = re.sub(r"\D", "", str(p))
            if len(cleaned) >= 9:
                return cleaned[-9:]
            return cleaned

        search_phone = _normalize_phone(phone_number) if phone_number else ""

        matched_tenant = None
        for tenant in tenants_data:
            # Match by phone
            if search_phone and _normalize_phone(tenant.get("phone", "")) == search_phone:
                matched_tenant = tenant
                break
            # Match by unit (case-insensitive)
            if unit and str(tenant.get("unit", "")).strip().lower() == str(unit).strip().lower():
                matched_tenant = tenant
                break
            # Match by name (partial, case-insensitive)
            if tenant_name and tenant_name.lower() in str(tenant.get("name", "")).lower():
                matched_tenant = tenant
                break

        if not matched_tenant:
            return {
                "success": False,
                "found": False,
                "error": "Tenant not found",
                "search_criteria": {
                    "phone": phone_number,
                    "name": tenant_name,
                    "unit": unit,
                },
            }

        return {
            "success": True,
            "found": True,
            "tenant": matched_tenant,
            "tenant_name": matched_tenant.get("name", "Unknown"),
            "tenant_phone": matched_tenant.get("phone", ""),
            "tenant_unit": matched_tenant.get("unit", ""),
            "rent_amount": float(matched_tenant.get("rent_amount", 0) or 0),
            "water_amount": float(matched_tenant.get("water_amount", 0) or 0),
            "electricity_amount": float(matched_tenant.get("electricity_amount", 0) or 0),
            "garbage_amount": float(matched_tenant.get("garbage_amount", 0) or 0),
            "balance": float(matched_tenant.get("balance", 0) or 0),
            "status": matched_tenant.get("status", "active"),
            "message": f"Found tenant: {matched_tenant.get('name', 'Unknown')} in Unit {matched_tenant.get('unit', 'N/A')}",
        }

    # ──────────────────────────────────────────────────────────────
    # 12. REGISTER TENANT
    # ──────────────────────────────────────────────────────────────

    async def register_tenant(
        self,
        tenant_name: str = "",
        phone_number: str = "",
        unit: str = "",
        property_name: str = "",
        rent_amount: float = 0,
        move_in_date: str = "",
        currency: str = "KES",
        language: str = "en",
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Auto-register a new tenant on first contact.

        Returns structured data that the conversational agent can use to
        append a row to Google Sheets / Airtable.
        """
        if not phone_number:
            return {"success": False, "error": "Phone number is required"}

        if not move_in_date:
            move_in_date = datetime.now().strftime("%d/%m/%Y")

        # Generate tenant record
        tenant_record = {
            "name": tenant_name or "New Tenant",
            "phone": phone_number,
            "unit": unit,
            "property_name": property_name,
            "rent_amount": rent_amount,
            "water_amount": 0,
            "electricity_amount": 0,
            "garbage_amount": 0,
            "balance": 0,
            "status": "active",
            "move_in_date": move_in_date,
            "registered_at": datetime.now().isoformat(),
        }

        # Welcome message
        if language == "sw":
            message = (
                f"🏠 *Karibu!*\n\n"
                f"Habari *{tenant_name or 'Mpangaji'}*,\n\n"
                f"Umesajiliwa kama mpangaji"
                + (f" wa *{unit}*" if unit else "")
                + (f" katika *{property_name}*" if property_name else "")
                + ".\n\n"
                + (f"💰 Kodi yako ya mwezi: *{self._fmt_amount(rent_amount, currency)}*\n\n" if rent_amount else "")
                + "Unaweza kutumia nambari hii kuuliza kuhusu:\n"
                f"  • 📋 Salio lako\n"
                f"  • 💳 Kulipa kodi na huduma\n"
                f"  • 🔧 Kuripoti tatizo la matengenezo\n\n"
                f"_Tuma ujumbe wowote kuanza!_ 💬"
            )
        else:
            message = (
                f"🏠 *Welcome!*\n\n"
                f"Hello *{tenant_name or 'Tenant'}*,\n\n"
                f"You have been registered as a tenant"
                + (f" of *{unit}*" if unit else "")
                + (f" at *{property_name}*" if property_name else "")
                + ".\n\n"
                + (f"💰 Your monthly rent: *{self._fmt_amount(rent_amount, currency)}*\n\n" if rent_amount else "")
                + "You can use this number to:\n"
                f"  • 📋 Check your balance\n"
                f"  • 💳 Pay rent & utilities\n"
                f"  • 🔧 Report maintenance issues\n\n"
                f"_Send any message to get started!_ 💬"
            )

        return {
            "success": True,
            "message": message,
            "tenant_record": tenant_record,
            "tenant_name": tenant_record["name"],
            "tenant_phone": phone_number,
            "tenant_unit": unit,
            "is_new_tenant": True,
        }


# Global instance
rent_collection_service = RentCollectionService()
