"""
Catalog Builder service.

Hosts product photos on the user's Google Drive (link-shareable) and writes
product rows into a Google Sheet in a schema the WhatsApp ordering agent's RAG
already understands. Supports creating a new sheet or appending to an existing
one (header-aware so columns map correctly regardless of order).

This service stops at sheet generation. RAG ingestion / search is handled by a
separate workflow.
"""

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Product photos live in this Drive folder (created on first use).
PRODUCT_PHOTOS_FOLDER = "Arrotech Product Photos"

# Tab + canonical headers compatible with rag_pipeline_service._rows_to_product_records.
PRODUCTS_SHEET_NAME = "Products"
CATALOG_HEADERS = ["name", "Price", "Description", "Category", "SKU", "Brand", "image_url", "Availability"]


def _normalize_header(header: str) -> str:
    """Lowercase + strip non-alphanumerics so 'Image URL' == 'image_url'."""
    return re.sub(r"[^a-z0-9]", "", (header or "").lower())


# Map normalized product-record keys to the canonical header they belong under.
_FIELD_TO_HEADER = {
    "name": "name",
    "price": "Price",
    "description": "Description",
    "category": "Category",
    "sku": "SKU",
    "brand": "Brand",
    "imageurl": "image_url",
    "availability": "Availability",
}


class CatalogBuilderError(Exception):
    """Raised for unrecoverable catalog build errors with a user-facing message."""


class CatalogBuilderService:
    """Drive photo hosting + Google Sheet catalog generation."""

    async def _get_connection_config(
        self, user_id: Any, db: AsyncSession
    ) -> Dict[str, Any]:
        from ..models import Connection, ConnectionStatus

        result = await db.execute(
            select(Connection).where(
                Connection.user_id == user_id,
                Connection.platform == "google_workspace",
                Connection.status == ConnectionStatus.ACTIVE,
            )
        )
        connection = result.scalar_one_or_none()
        if not connection or not connection.config:
            raise CatalogBuilderError(
                "Google Workspace is not connected. Connect it under Integrations to continue."
            )

        config = connection.config
        if not all(
            [
                config.get("client_id"),
                config.get("client_secret"),
                config.get("refresh_token"),
            ]
        ):
            raise CatalogBuilderError(
                "Google Workspace credentials are incomplete. Please reconnect the integration."
            )
        return config

    def _build_services(self, config: Dict[str, Any]):
        from .google_workspace.base_client import GoogleWorkspaceBaseClient
        from .google_workspace.drive_service import DriveService
        from .google_workspace.sheets_service import SheetsService

        credentials_data = {
            "client_id": config.get("client_id"),
            "client_secret": config.get("client_secret"),
            "refresh_token": config.get("refresh_token"),
            "access_token": config.get("access_token"),
            "scopes": config.get("scopes"),
        }
        base_client = GoogleWorkspaceBaseClient(credentials_data)
        return DriveService(base_client), SheetsService(base_client)

    async def list_spreadsheets(self, user_id: Any, db: AsyncSession, folder_id: Optional[str] = None) -> List[Dict[str, str]]:
        config = await self._get_connection_config(user_id, db)
        drive_service, _ = self._build_services(config)
        result = await drive_service.list_spreadsheets(folder_id=folder_id)
        if not result.get("success"):
            raise CatalogBuilderError(result.get("error", "Failed to list spreadsheets"))
        return [
            {"id": opt.get("value"), "name": opt.get("label")}
            for opt in result.get("options", [])
        ]

    async def _ensure_photos_folder(self, drive_service) -> Optional[str]:
        """Find or create the product photos folder. Returns folder id or None."""
        try:
            existing = await drive_service.list_files(
                query=(
                    "mimeType = 'application/vnd.google-apps.folder' "
                    f"and name = '{PRODUCT_PHOTOS_FOLDER}' and trashed = false"
                ),
                max_results=1,
            )
            files = existing.get("files") or existing.get("data") or []
            if isinstance(files, list) and files:
                first = files[0]
                folder_id = first.get("id") if isinstance(first, dict) else None
                if folder_id:
                    return folder_id
        except Exception as e:
            logger.warning(f"[CATALOG] Folder lookup failed (will create): {e}")

        created = await drive_service.create_folder(PRODUCT_PHOTOS_FOLDER)
        if created.get("success"):
            return created.get("folder_id")
        logger.warning(f"[CATALOG] Folder create failed: {created.get('error')}")
        return None

    async def upload_product_image(
        self,
        drive_service,
        folder_id: Optional[str],
        filename: str,
        content: bytes,
        mime_type: str,
    ) -> Dict[str, Any]:
        """Upload one photo and make it link-public. Returns {file_id, direct_url}."""
        upload = await drive_service.upload_file(
            filename=filename,
            content=content,
            mime_type=mime_type or "image/jpeg",
            folder_id=folder_id,
        )
        if not upload.get("success"):
            return {"success": False, "error": upload.get("error", "Upload failed")}

        file_id = upload.get("file_id")
        public = await drive_service.make_public(file_id)
        if not public.get("success"):
            return {
                "success": False,
                "error": public.get("error", "Could not make photo public"),
                "file_id": file_id,
            }
        return {
            "success": True,
            "file_id": file_id,
            "direct_url": public.get("direct_url"),
        }

    async def _resolve_headers(
        self, sheets_service, spreadsheet_id: str, sheet_name: str
    ) -> Tuple[str, List[str]]:
        """
        Ensure a usable header row exists on `sheet_name`. If the tab has no
        header row, write CATALOG_HEADERS. Returns (sheet_name, headers).
        """
        read = await sheets_service.read_range(
            spreadsheet_id, f"{sheet_name}!A1:ZZ1"
        )
        if read.get("success"):
            values = read.get("values") or []
            if values and values[0]:
                header_row = [str(h) for h in values[0]]
                # Remove trailing empty columns only
                while header_row and not header_row[-1].strip():
                    header_row.pop()
                if header_row:
                    return sheet_name, header_row

        # No headers yet — write canonical headers.
        write = await sheets_service.write_range(
            spreadsheet_id, f"{sheet_name}!A1", [CATALOG_HEADERS]
        )
        if not write.get("success"):
            raise CatalogBuilderError(
                write.get("error", "Failed to write header row")
            )
        return sheet_name, list(CATALOG_HEADERS)

    def _record_to_row(self, record: Dict[str, Any], headers: List[str]) -> List[str]:
        """Align a product record to the sheet's header columns."""
        # Map canonical header -> value from the record.
        header_value: Dict[str, str] = {}
        for field, value in record.items():
            canonical = _FIELD_TO_HEADER.get(_normalize_header(field))
            if canonical is None:
                continue
            header_value[_normalize_header(canonical)] = "" if value is None else str(value)

        row: List[str] = []
        for h in headers:
            h_str = h.strip()
            if not h_str:
                row.append("")
            else:
                row.append(header_value.get(_normalize_header(h_str), ""))
        return row

    async def write_products(
        self,
        sheets_service,
        spreadsheet_id: str,
        sheet_name: str,
        products: List[Dict[str, Any]],
    ) -> int:
        """Append product rows aligned to the sheet headers. Returns rows written."""
        target_sheet, headers = await self._resolve_headers(
            sheets_service, spreadsheet_id, sheet_name
        )
        rows = [self._record_to_row(p, headers) for p in products]
        if not rows:
            return 0
        # Instead of using append_rows (which is notoriously buggy if there are formulas/formatting
        # anywhere in the sheet), we manually find the last row by reading the Name column.
        name_idx = 0
        for i, h in enumerate(headers):
            if _normalize_header(h) == "name":
                name_idx = i
                break
        
        name_col = chr(ord('A') + min(name_idx, 25))
        
        col_read = await sheets_service.read_range(
            spreadsheet_id, f"{target_sheet}!{name_col}:{name_col}"
        )
        
        last_row = 0
        if col_read.get("success"):
            col_values = col_read.get("values") or []
            for i, row_val in enumerate(col_values):
                if row_val and len(row_val) > 0 and str(row_val[0]).strip():
                    last_row = i + 1
        
        next_row = max(last_row + 1, 2)
        
        write = await sheets_service.write_range(
            spreadsheet_id, f"{target_sheet}!A{next_row}", rows
        )
        if not write.get("success"):
            raise CatalogBuilderError(write.get("error", "Failed to write product rows"))
        return len(rows)

    async def export_catalog(
        self,
        user_id: Any,
        db: AsyncSession,
        products: List[Dict[str, Any]],
        target: Dict[str, Any],
        want_csv: bool = False,
    ) -> Dict[str, Any]:
        """
        products: list of dicts, each may include an `_image` key:
            {"content": bytes, "mime_type": str, "filename": str}
        target: {"mode": "new"|"append", "title": str?, "spreadsheet_id": str?}

        Returns { spreadsheet_id, spreadsheet_url, rows_written, csv_base64? }.
        """
        if not products:
            raise CatalogBuilderError("No products to export.")

        config = await self._get_connection_config(user_id, db)
        drive_service, sheets_service = self._build_services(config)

        # 1. Host photos on Drive (best-effort per product; track for cleanup).
        folder_id = await self._ensure_photos_folder(drive_service)
        uploaded_file_ids: List[str] = []
        rows: List[Dict[str, Any]] = []

        try:
            for idx, product in enumerate(products):
                record = {
                    "name": product.get("name", ""),
                    "Price": product.get("price", ""),
                    "Description": product.get("description", ""),
                    "Category": product.get("category", ""),
                    "SKU": product.get("sku", ""),
                    "Brand": product.get("brand", ""),
                    "image_url": product.get("image_url", ""),
                    "Availability": product.get("availability", ""),
                }

                image = product.get("_image")
                if image and image.get("content"):
                    filename = image.get("filename") or f"product_{idx + 1}.jpg"
                    up = await self.upload_product_image(
                        drive_service,
                        folder_id,
                        filename,
                        image["content"],
                        image.get("mime_type", "image/jpeg"),
                    )
                    if up.get("success"):
                        if up.get("file_id"):
                            uploaded_file_ids.append(up["file_id"])
                        record["image_url"] = up.get("direct_url", "")
                    else:
                        # Non-fatal: keep the row without a hosted image.
                        logger.warning(
                            f"[CATALOG] Image host failed for product {idx + 1}: {up.get('error')}"
                        )
                rows.append(record)

            # 2. Resolve target spreadsheet.
            mode = (target or {}).get("mode", "new")
            if mode == "append":
                spreadsheet_id = (target or {}).get("spreadsheet_id")
                if not spreadsheet_id:
                    raise CatalogBuilderError("No spreadsheet selected to append to.")
                info = await sheets_service.get_spreadsheet_info(spreadsheet_id)
                if not info.get("success"):
                    raise CatalogBuilderError(
                        info.get("error", "Could not open the selected spreadsheet.")
                    )
                spreadsheet_url = info.get("spreadsheet_url", "")
                # Prefer an existing "Products" tab, else the first tab.
                tab_titles = [s.get("title") for s in info.get("sheets", []) if s.get("title")]
                sheet_name = (
                    PRODUCTS_SHEET_NAME
                    if PRODUCTS_SHEET_NAME in tab_titles
                    else (tab_titles[0] if tab_titles else PRODUCTS_SHEET_NAME)
                )
            else:
                title = (target or {}).get("title") or "Product Catalog"
                target_folder_id = (target or {}).get("folder_id")
                created = await sheets_service.create_spreadsheet(
                    title=title, sheets=[PRODUCTS_SHEET_NAME]
                )
                if not created.get("success"):
                    raise CatalogBuilderError(
                        created.get("error", "Failed to create spreadsheet.")
                    )
                spreadsheet_id = created.get("spreadsheet_id")
                spreadsheet_url = created.get("spreadsheet_url", "")
                sheet_name = PRODUCTS_SHEET_NAME
                
                # Move to the selected folder if specified
                if target_folder_id:
                    try:
                        await drive_service.move_file(spreadsheet_id, target_folder_id)
                    except Exception as e:
                        logger.warning(f"[CATALOG] Failed to move spreadsheet to folder {target_folder_id}: {e}")

            # 3. Write rows.
            rows_written = await self.write_products(
                sheets_service, spreadsheet_id, sheet_name, rows
            )

            result: Dict[str, Any] = {
                "success": True,
                "spreadsheet_id": spreadsheet_id,
                "spreadsheet_url": spreadsheet_url,
                "rows_written": rows_written,
                "csv_available": False,
            }

            # 4. Optional CSV export.
            if want_csv:
                try:
                    import base64

                    dl = await drive_service.download_file(spreadsheet_id)
                    if dl.get("success") and dl.get("content"):
                        result["csv_base64"] = base64.b64encode(dl["content"]).decode("ascii")
                        result["csv_available"] = True
                except Exception as e:
                    logger.warning(f"[CATALOG] CSV export failed (non-fatal): {e}")

            return result

        except Exception as e:
            # Cleanup orphan Drive photos on a failed export so we don't litter.
            for file_id in uploaded_file_ids:
                try:
                    await drive_service.delete_file(file_id)
                except Exception:
                    pass
            if isinstance(e, CatalogBuilderError):
                raise
            logger.error(f"[CATALOG] export_catalog failed: {e}", exc_info=True)
            raise CatalogBuilderError(str(e))


catalog_builder_service = CatalogBuilderService()
