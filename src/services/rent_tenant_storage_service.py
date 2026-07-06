"""Google Sheets persistence for WhatsApp rent collection agents."""
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from ..models import User
from .cache_service import cache_service

logger = logging.getLogger(__name__)

TENANTS_HEADERS = [
    "name",
    "phone",
    "unit",
    "rent_amount",
    "water_amount",
    "electricity_amount",
    "garbage_amount",
    "balance",
    "status",
    "move_in_date",
    "property_name",
]

PAYMENTS_HEADERS = [
    "timestamp",
    "tenant_name",
    "unit",
    "phone",
    "amount_paid",
    "total_bill",
    "balance_after",
    "transaction_id",
    "method",
    "period",
]


def storage_config_from_business(business_config: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "spreadsheet_id": (business_config.get("storage_spreadsheet_id") or "").strip(),
        "tenants_sheet_name": (
            business_config.get("storage_tenants_sheet_name") or "Tenants"
        ).strip()
        or "Tenants",
        "payments_sheet_name": (
            business_config.get("storage_payments_sheet_name") or "Payments"
        ).strip()
        or "Payments",
    }


def _normalize_phone(p: str) -> str:
    cleaned = re.sub(r"\D", "", str(p or ""))
    if len(cleaned) >= 9:
        return cleaned[-9:]
    return cleaned


def _rows_to_tenants(values: List[List[Any]]) -> List[Dict[str, Any]]:
    if not values:
        return []

    first_row = [str(h or "").strip().lower() for h in values[0]]
    data_start = 1
    headers = first_row

    # If row 1 is tenant data (not column headers), use the standard schema.
    if not headers or headers[0] != "name":
        headers = [h.lower() for h in TENANTS_HEADERS]
        data_start = 0

    if data_start >= len(values):
        return []

    tenants: List[Dict[str, Any]] = []
    for row in values[data_start:]:
        if not any(str(c or "").strip() for c in row):
            continue
        record: Dict[str, Any] = {}
        for idx, header in enumerate(headers):
            if not header:
                continue
            record[header] = row[idx] if idx < len(row) else ""
        if record.get("phone") or record.get("unit") or record.get("name"):
            tenants.append(record)
    return tenants


def _values_from_sheet_read(read_res: Dict[str, Any]) -> List[List[Any]]:
    """Unwrap sheet read results from ToolExecutor (flat or nested)."""
    if not isinstance(read_res, dict):
        return []
    if read_res.get("values"):
        return read_res.get("values") or []
    inner = read_res.get("result")
    if isinstance(inner, dict) and inner.get("values"):
        return inner.get("values") or []
    return []


class RentTenantStorageService:
    """Load and persist tenant/payment rows in Google Sheets."""

    def _cache_key(self, user_id: str, spreadsheet_id: str) -> str:
        return f"rent:tenants:{user_id}:{spreadsheet_id}"

    async def load_tenants(
        self,
        user: User,
        business_config: Dict[str, Any],
        db: AsyncSession,
        *,
        force_refresh: bool = False,
    ) -> List[Dict[str, Any]]:
        cfg = storage_config_from_business(business_config)
        spreadsheet_id = cfg.get("spreadsheet_id")
        if not spreadsheet_id:
            return []

        cache_key = self._cache_key(str(user.id), spreadsheet_id)
        if not force_refresh:
            cached = cache_service.get(cache_key)
            if isinstance(cached, list):
                return cached

        from .tool_executor import ToolExecutor

        executor = ToolExecutor()
        sheet_name = cfg["tenants_sheet_name"]
        read_res = await executor.execute_tool(
            "google_workspace_sheets",
            {
                "operation": "read_range",
                "spreadsheet_id": spreadsheet_id,
                "range_name": f"{sheet_name}!A:ZZ",
            },
            user,
            db,
        )
        if not read_res.get("success"):
            logger.warning("[RENT_STORAGE] Failed to read tenants sheet: %s", read_res.get("error"))
            return []

        tenants = _rows_to_tenants(_values_from_sheet_read(read_res))
        if not tenants:
            logger.warning(
                "[RENT_STORAGE] No tenants parsed from sheet %s tab %s (rows=%s)",
                spreadsheet_id,
                sheet_name,
                len(_values_from_sheet_read(read_res)),
            )
        cache_service.set(cache_key, tenants, expire_seconds=60)
        return tenants

    def invalidate_cache(self, user_id: str, spreadsheet_id: str) -> None:
        cache_service.delete(self._cache_key(user_id, spreadsheet_id))

    async def ensure_sheets_exist(
        self,
        user: User,
        spreadsheet_id: str,
        db: AsyncSession,
        *,
        tenants_sheet: str = "Tenants",
        payments_sheet: str = "Payments",
    ) -> Dict[str, Any]:
        from .tool_executor import ToolExecutor

        executor = ToolExecutor()
        for sheet_name, headers in (
            (tenants_sheet, TENANTS_HEADERS),
            (payments_sheet, PAYMENTS_HEADERS),
        ):
            await executor.execute_tool(
                "google_workspace_sheets",
                {
                    "operation": "write_range",
                    "spreadsheet_id": spreadsheet_id,
                    "range_name": f"{sheet_name}!A1",
                    "values": [headers],
                },
                user,
                db,
            )
        return {"success": True, "spreadsheet_id": spreadsheet_id}

    async def bootstrap_spreadsheet(
        self,
        user: User,
        db: AsyncSession,
        *,
        title: str = "Rent Collection",
        include_sample: bool = True,
    ) -> Dict[str, Any]:
        from .tool_executor import ToolExecutor

        executor = ToolExecutor()
        created = await executor.execute_tool(
            "google_workspace_sheets",
            {
                "operation": "create_spreadsheet",
                "title": title,
                "sheets": ["Tenants", "Payments"],
            },
            user,
            db,
        )
        if not created.get("success"):
            return {"success": False, "error": created.get("error", "Failed to create spreadsheet")}

        spreadsheet_id = created.get("spreadsheet_id") or created.get("result", {}).get(
            "spreadsheet_id"
        )
        if not spreadsheet_id and isinstance(created.get("result"), dict):
            spreadsheet_id = created["result"].get("spreadsheet_id")
        spreadsheet_url = created.get("spreadsheet_url") or ""
        if not spreadsheet_url and isinstance(created.get("result"), dict):
            spreadsheet_url = created["result"].get("spreadsheet_url", "")

        if not spreadsheet_id:
            return {"success": False, "error": "Spreadsheet created but ID missing"}

        await self.ensure_sheets_exist(user, spreadsheet_id, db)

        if include_sample:
            await executor.execute_tool(
                "google_workspace_sheets",
                {
                    "operation": "append_rows",
                    "spreadsheet_id": spreadsheet_id,
                    "range_name": "Tenants!A:K",
                    "values": [
                        [
                            "Jane Doe",
                            "254712345678",
                            "A12",
                            "15000",
                            "500",
                            "800",
                            "300",
                            "0",
                            "active",
                            datetime.utcnow().strftime("%d/%m/%Y"),
                            title,
                        ]
                    ],
                },
                user,
                db,
            )

        return {
            "success": True,
            "spreadsheet_id": spreadsheet_id,
            "spreadsheet_url": spreadsheet_url,
        }

    async def append_payment_row(
        self,
        user: User,
        business_config: Dict[str, Any],
        db: AsyncSession,
        *,
        tenant_name: str,
        unit: str,
        phone: str,
        amount_paid: float,
        total_bill: float,
        balance_after: float,
        transaction_id: str = "",
        method: str = "M-Pesa",
        period: str = "",
    ) -> None:
        cfg = storage_config_from_business(business_config)
        spreadsheet_id = cfg.get("spreadsheet_id")
        if not spreadsheet_id:
            return

        from .tool_executor import ToolExecutor

        executor = ToolExecutor()
        if not period:
            period = datetime.utcnow().strftime("%B %Y")

        await executor.execute_tool(
            "google_workspace_sheets",
            {
                "operation": "append_rows",
                "spreadsheet_id": spreadsheet_id,
                "range_name": f"{cfg['payments_sheet_name']}!A:J",
                "values": [
                    [
                        datetime.utcnow().isoformat(),
                        tenant_name,
                        unit,
                        phone,
                        amount_paid,
                        total_bill,
                        balance_after,
                        transaction_id,
                        method,
                        period,
                    ]
                ],
            },
            user,
            db,
        )
        self.invalidate_cache(str(user.id), spreadsheet_id)

    async def update_tenant_balance(
        self,
        user: User,
        business_config: Dict[str, Any],
        db: AsyncSession,
        *,
        unit: str,
        new_balance: float,
    ) -> None:
        cfg = storage_config_from_business(business_config)
        spreadsheet_id = cfg.get("spreadsheet_id")
        if not spreadsheet_id or not unit:
            return

        from .tool_executor import ToolExecutor

        executor = ToolExecutor()
        sheet_name = cfg["tenants_sheet_name"]
        read_res = await executor.execute_tool(
            "google_workspace_sheets",
            {
                "operation": "read_range",
                "spreadsheet_id": spreadsheet_id,
                "range_name": f"{sheet_name}!A:ZZ",
            },
            user,
            db,
        )
        if not read_res.get("success"):
            return

        values = _values_from_sheet_read(read_res)
        if not values:
            return []

        first_row = [str(h or "").strip().lower() for h in values[0]]
        data_start = 1
        headers = first_row
        if not headers or headers[0] != "name":
            headers = [h.lower() for h in TENANTS_HEADERS]
            data_start = 0

        unit_idx = headers.index("unit") if "unit" in headers else -1
        balance_idx = headers.index("balance") if "balance" in headers else -1
        if unit_idx < 0 or balance_idx < 0:
            return

        target_row = None
        for row_num, row in enumerate(values[data_start:], start=data_start + 1):
            cell = str(row[unit_idx] if unit_idx < len(row) else "").strip().lower()
            if cell == str(unit).strip().lower():
                target_row = row_num
                break

        if not target_row:
            return

        col_letter = chr(ord("A") + balance_idx)
        await executor.execute_tool(
            "google_workspace_sheets",
            {
                "operation": "write_range",
                "spreadsheet_id": spreadsheet_id,
                "range_name": f"{sheet_name}!{col_letter}{target_row}",
                "values": [[new_balance]],
            },
            user,
            db,
        )
        self.invalidate_cache(str(user.id), spreadsheet_id)

    async def append_tenant_row(
        self,
        user: User,
        business_config: Dict[str, Any],
        db: AsyncSession,
        tenant_record: Dict[str, Any],
    ) -> None:
        cfg = storage_config_from_business(business_config)
        spreadsheet_id = cfg.get("spreadsheet_id")
        if not spreadsheet_id:
            return

        from .tool_executor import ToolExecutor

        executor = ToolExecutor()
        await executor.execute_tool(
            "google_workspace_sheets",
            {
                "operation": "append_rows",
                "spreadsheet_id": spreadsheet_id,
                "range_name": f"{cfg['tenants_sheet_name']}!A:K",
                "values": [
                    [
                        tenant_record.get("name", ""),
                        tenant_record.get("phone", ""),
                        tenant_record.get("unit", ""),
                        tenant_record.get("rent_amount", 0),
                        tenant_record.get("water_amount", 0),
                        tenant_record.get("electricity_amount", 0),
                        tenant_record.get("garbage_amount", 0),
                        tenant_record.get("balance", 0),
                        tenant_record.get("status", "active"),
                        tenant_record.get("move_in_date", ""),
                        tenant_record.get("property_name", ""),
                    ]
                ],
            },
            user,
            db,
        )
        self.invalidate_cache(str(user.id), spreadsheet_id)


rent_tenant_storage_service = RentTenantStorageService()
