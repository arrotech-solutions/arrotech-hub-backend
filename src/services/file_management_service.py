"""
File Management Service for handling file operations, PDF generation, and document conversion.
"""

import asyncio
import base64
import io
import logging
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
import uuid
from urllib.parse import urlparse

import aiofiles
import aiohttp
import markdown
import qrcode
from fastapi import UploadFile
from PIL import Image
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4, letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# Try to import WeasyPrint, but make it optional
try:
    from weasyprint import HTML
    WEASYPRINT_AVAILABLE = True
except ImportError:
    WEASYPRINT_AVAILABLE = False
    print("Warning: WeasyPrint not available. Using ReportLab for PDF generation.")

logger = logging.getLogger(__name__)


class FileManagementService:
    """Service for file operations, PDF generation, and document management."""
    
    def __init__(self):
        # Try different paths for uploads directory
        upload_paths = [
            Path("/app/uploads"),
            Path("/tmp/uploads"),
            Path("/tmp"),
            Path.home() / "uploads"
        ]
        
        # Find a writable upload directory
        self.upload_dir = None
        for path in upload_paths:
            try:
                path.mkdir(exist_ok=True)
                # Test if we can write to it
                test_file = path / ".test"
                test_file.touch()
                test_file.unlink()
                self.upload_dir = path
                break
            except (PermissionError, OSError):
                continue
        
        if self.upload_dir is None:
            # Last resort: use current directory
            self.upload_dir = Path.cwd() / "uploads"
            self.upload_dir.mkdir(exist_ok=True)
        
        # Use /tmp for temporary files
        self.temp_dir = Path("/tmp")
        self.temp_dir.mkdir(exist_ok=True)
        
        logger.info(f"File management service initialized with upload_dir: {self.upload_dir}")
    
    async def generate_pdf_from_html(self, html_content: str, filename: str = None) -> Dict[str, Any]:
        """Generate PDF from HTML content."""
        try:
            if not filename:
                filename = f"document_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
            
            pdf_path = self.temp_dir / filename
            
            if WEASYPRINT_AVAILABLE:
                # Use WeasyPrint if available
                html_doc = HTML(string=html_content)
                html_doc.write_pdf(str(pdf_path))
            else:
                # Fallback to ReportLab
                await self._generate_pdf_with_reportlab(html_content, pdf_path)
            
            # Read the generated PDF
            async with aiofiles.open(pdf_path, 'rb') as f:
                pdf_content = await f.read()
            
            # Clean up temp file
            pdf_path.unlink(missing_ok=True)
            
            return {
                "success": True,
                "filename": filename,
                "content": base64.b64encode(pdf_content).decode(),
                "size": len(pdf_content),
                "method": "weasyprint" if WEASYPRINT_AVAILABLE else "reportlab"
            }
        except Exception as e:
            logger.error(f"Error generating PDF from HTML: {e}")
            return {"success": False, "error": str(e)}

    async def generate_order_receipt_pdf(
        self,
        receipt_data: Dict[str, Any],
        filename: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Generate a styled order receipt PDF (ReportLab — no HTML/CSS stripping)."""
        try:
            if not filename:
                order_id = receipt_data.get("order_id", "order")
                suffix = "PAID" if receipt_data.get("payment_status") == "paid" else "receipt"
                filename = f"receipt_{order_id}_{suffix}.pdf"

            pdf_bytes = self._build_order_receipt_pdf_bytes(receipt_data)
            return {
                "success": True,
                "filename": filename,
                "content": base64.b64encode(pdf_bytes).decode(),
                "size": len(pdf_bytes),
                "method": "reportlab_receipt",
            }
        except Exception as e:
            logger.error(f"Error generating order receipt PDF: {e}")
            return {"success": False, "error": str(e)}

    @staticmethod
    def _format_receipt_qty(quantity: Any) -> str:
        try:
            qty = float(quantity)
            if qty == int(qty):
                return str(int(qty))
            return f"{qty:g}"
        except (TypeError, ValueError):
            return str(quantity or 1)

    @staticmethod
    def _format_receipt_money(amount: Any, currency: str) -> str:
        try:
            value = float(amount)
            if value == int(value):
                return f"{currency} {int(value):,}"
            return f"{currency} {value:,.2f}"
        except (TypeError, ValueError):
            return f"{currency} 0"

    def _build_order_receipt_pdf_bytes(self, data: Dict[str, Any]) -> bytes:
        """Build a professional receipt PDF using ReportLab layout primitives."""
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            leftMargin=18 * mm,
            rightMargin=18 * mm,
            topMargin=16 * mm,
            bottomMargin=16 * mm,
            title=f"Receipt {data.get('order_id', '')}",
        )

        payment_status = data.get("payment_status", "pending")
        is_paid = payment_status == "paid"
        accent = colors.HexColor("#16a34a") if is_paid else colors.HexColor("#2563eb")
        accent_light = colors.HexColor("#dcfce7") if is_paid else colors.HexColor("#dbeafe")
        badge_text = "PAID" if is_paid else "ORDER RECEIVED"
        total_label = "Total Paid" if is_paid else "Total Due"
        currency = data.get("currency", "KES")
        business_name = str(data.get("business_name") or "Business")
        order_id = str(data.get("order_id") or "")
        issued_at = data.get("issued_at") or datetime.utcnow().strftime("%d %b %Y, %H:%M UTC")

        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            "ReceiptTitle",
            parent=styles["Heading1"],
            fontSize=20,
            leading=24,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#111827"),
            spaceAfter=4,
        )
        subtitle_style = ParagraphStyle(
            "ReceiptSubtitle",
            parent=styles["Normal"],
            fontSize=9,
            leading=12,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#6b7280"),
        )
        label_style = ParagraphStyle(
            "ReceiptLabel",
            parent=styles["Normal"],
            fontSize=9,
            leading=12,
            textColor=colors.HexColor("#6b7280"),
        )
        value_style = ParagraphStyle(
            "ReceiptValue",
            parent=styles["Normal"],
            fontSize=9,
            leading=12,
            textColor=colors.HexColor("#111827"),
        )
        footer_style = ParagraphStyle(
            "ReceiptFooter",
            parent=styles["Normal"],
            fontSize=8,
            leading=11,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#9ca3af"),
        )

        story: List[Any] = []

        # Header
        story.append(Paragraph(business_name, title_style))
        badge_table = Table(
            [[Paragraph(f"<b>{badge_text}</b>", ParagraphStyle(
                "Badge",
                parent=styles["Normal"],
                fontSize=9,
                textColor=colors.white,
                alignment=TA_CENTER,
            ))]],
            colWidths=[doc.width * 0.42],
            hAlign="CENTER",
        )
        badge_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), accent),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
            ("ROUNDEDCORNERS", [4, 4, 4, 4]),
        ]))
        story.append(badge_table)
        story.append(Spacer(1, 6))
        story.append(Paragraph("Official order receipt", subtitle_style))
        story.append(Spacer(1, 10))
        story.append(HRFlowable(width="100%", thickness=1.5, color=accent, spaceAfter=12))

        # Order meta (two-column)
        meta_rows = [
            [Paragraph("Order No.", label_style), Paragraph(f"<b>{order_id}</b>", value_style)],
            [Paragraph("Date", label_style), Paragraph(issued_at, value_style)],
        ]
        customer_name = data.get("customer_name")
        customer_phone = data.get("customer_phone")
        delivery_method = data.get("delivery_method")
        delivery_address = data.get("delivery_address")
        business_phone = data.get("business_phone")
        mpesa_receipt = data.get("mpesa_receipt")

        if customer_name:
            meta_rows.append([
                Paragraph("Customer", label_style),
                Paragraph(str(customer_name), value_style),
            ])
        if customer_phone:
            meta_rows.append([
                Paragraph("Phone", label_style),
                Paragraph(str(customer_phone), value_style),
            ])
        if delivery_method:
            meta_rows.append([
                Paragraph("Delivery", label_style),
                Paragraph(str(delivery_method).replace("_", " ").title(), value_style),
            ])
        if delivery_address:
            meta_rows.append([
                Paragraph("Address", label_style),
                Paragraph(str(delivery_address), value_style),
            ])
        if business_phone:
            meta_rows.append([
                Paragraph("Business", label_style),
                Paragraph(str(business_phone), value_style),
            ])
        if is_paid and mpesa_receipt:
            meta_rows.append([
                Paragraph("M-Pesa Ref", label_style),
                Paragraph(f"<b>{mpesa_receipt}</b>", value_style),
            ])

        meta_table = Table(meta_rows, colWidths=[doc.width * 0.28, doc.width * 0.72])
        meta_table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(meta_table)
        story.append(Spacer(1, 12))

        # Line items
        items = data.get("items") or []
        table_data = [
            [
                Paragraph("<b>Item</b>", value_style),
                Paragraph("<b>Qty</b>", ParagraphStyle("QtyH", parent=value_style, alignment=TA_CENTER)),
                Paragraph("<b>Unit</b>", ParagraphStyle("UnitH", parent=value_style, alignment=TA_RIGHT)),
                Paragraph("<b>Total</b>", ParagraphStyle("TotH", parent=value_style, alignment=TA_RIGHT)),
            ]
        ]
        for item in items:
            name = str(item.get("name", "Item"))
            qty = self._format_receipt_qty(item.get("quantity", 1))
            unit = float(item.get("unit_price", 0) or item.get("price", 0) or 0)
            line_total = float(item.get("total", 0) or (float(item.get("quantity", 1) or 1) * unit))
            table_data.append([
                Paragraph(name, value_style),
                Paragraph(qty, ParagraphStyle("Qty", parent=value_style, alignment=TA_CENTER)),
                Paragraph(self._format_receipt_money(unit, currency), ParagraphStyle("Unit", parent=value_style, alignment=TA_RIGHT)),
                Paragraph(self._format_receipt_money(line_total, currency), ParagraphStyle("Line", parent=value_style, alignment=TA_RIGHT)),
            ])

        if len(table_data) == 1:
            table_data.append([
                Paragraph("Order items", value_style),
                Paragraph("—", ParagraphStyle("QtyE", parent=value_style, alignment=TA_CENTER)),
                Paragraph("—", ParagraphStyle("UnitE", parent=value_style, alignment=TA_RIGHT)),
                Paragraph(self._format_receipt_money(data.get("amount", 0), currency), ParagraphStyle("LineE", parent=value_style, alignment=TA_RIGHT)),
            ])

        items_table = Table(
            table_data,
            colWidths=[doc.width * 0.44, doc.width * 0.10, doc.width * 0.23, doc.width * 0.23],
            repeatRows=1,
        )
        items_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), accent_light),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#111827")),
            ("LINEBELOW", (0, 0), (-1, 0), 1, accent),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f9fafb")]),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#e5e7eb")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ]))
        story.append(items_table)
        story.append(Spacer(1, 10))

        amount = data.get("amount", 0)
        total_table = Table(
            [[
                Paragraph(f"<b>{total_label}</b>", ParagraphStyle(
                    "TotalLabel",
                    parent=value_style,
                    fontSize=11,
                    alignment=TA_RIGHT,
                )),
                Paragraph(
                    f"<b>{self._format_receipt_money(amount, currency)}</b>",
                    ParagraphStyle(
                        "TotalValue",
                        parent=value_style,
                        fontSize=12,
                        alignment=TA_RIGHT,
                        textColor=accent,
                    ),
                ),
            ]],
            colWidths=[doc.width * 0.62, doc.width * 0.38],
        )
        total_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), accent_light),
            ("BOX", (0, 0), (-1, -1), 0.5, accent),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ]))
        story.append(total_table)
        story.append(Spacer(1, 18))
        story.append(HRFlowable(width="40%", thickness=0.5, color=colors.HexColor("#e5e7eb"), spaceAfter=8, hAlign="CENTER"))
        story.append(Paragraph("Thank you for your business!", footer_style))
        story.append(Paragraph("This is a computer-generated receipt.", footer_style))

        doc.build(story)
        return buffer.getvalue()
    
    async def _generate_pdf_with_reportlab(self, html_content: str, pdf_path: Path) -> None:
        """Generate PDF using ReportLab as fallback."""
        try:
            import re

            # Strip style/script blocks first — tag stripping alone leaves raw CSS in the PDF
            text_content = re.sub(
                r"<(style|script)[^>]*>.*?</\1>",
                "",
                html_content,
                flags=re.IGNORECASE | re.DOTALL,
            )
            text_content = re.sub(r"<[^>]+>", "", text_content)
            text_content = re.sub(r"\s+", " ", text_content).strip()
            
            # Create PDF with ReportLab
            doc = SimpleDocTemplate(str(pdf_path), pagesize=letter)
            styles = getSampleStyleSheet()
            story = []
            
            # Split content into paragraphs
            paragraphs = text_content.split('\n\n')
            for para in paragraphs:
                if para.strip():
                    story.append(Paragraph(para.strip(), styles['Normal']))
                    story.append(Spacer(1, 12))
            
            doc.build(story)
        except Exception as e:
            logger.error(f"Error generating PDF with ReportLab: {e}")
            raise
    
    async def generate_pdf_from_markdown(self, markdown_content: str, filename: str = None) -> Dict[str, Any]:
        """Generate PDF from markdown content."""
        try:
            # Convert markdown to HTML
            html_content = markdown.markdown(markdown_content)
            
            # Add basic styling
            styled_html = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <style>
                    body {{ font-family: Arial, sans-serif; margin: 40px; }}
                    h1, h2, h3 {{ color: #333; }}
                    code {{ background-color: #f4f4f4; padding: 2px 4px; }}
                    pre {{ background-color: #f4f4f4; padding: 10px; }}
                </style>
            </head>
            <body>
                {html_content}
            </body>
            </html>
            """
            
            return await self.generate_pdf_from_html(styled_html, filename)
        except Exception as e:
            logger.error(f"Error generating PDF from markdown: {e}")
            return {"success": False, "error": str(e)}
    
    async def generate_pdf_from_data(self, data: Dict[str, Any], template: str = "default") -> Dict[str, Any]:
        """Generate PDF from structured data using templates."""
        try:
            if template == "default":
                html_content = self._generate_default_template(data)
            else:
                html_content = self._generate_custom_template(data, template)
            
            filename = f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
            return await self.generate_pdf_from_html(html_content, filename)
        except Exception as e:
            logger.error(f"Error generating PDF from data: {e}")
            return {"success": False, "error": str(e)}
    
    def _generate_default_template(self, data: Dict[str, Any]) -> str:
        """Generate default HTML template from data."""
        html_parts = ["<html><head><style>body{font-family:Arial;margin:20px;}</style></head><body>"]
        
        if "title" in data:
            html_parts.append(f"<h1>{data['title']}</h1>")
        
        if "content" in data:
            if isinstance(data["content"], list):
                for item in data["content"]:
                    html_parts.append(f"<p>{item}</p>")
            else:
                html_parts.append(f"<p>{data['content']}</p>")
        
        if "table" in data:
            html_parts.append("<table border='1' style='border-collapse:collapse;width:100%;'>")
            if "headers" in data["table"]:
                html_parts.append("<tr>")
                for header in data["table"]["headers"]:
                    html_parts.append(f"<th style='padding:8px;'>{header}</th>")
                html_parts.append("</tr>")
            
            if "rows" in data["table"]:
                for row in data["table"]["rows"]:
                    html_parts.append("<tr>")
                    for cell in row:
                        html_parts.append(f"<td style='padding:8px;'>{cell}</td>")
                    html_parts.append("</tr>")
            html_parts.append("</table>")
        
        html_parts.append("</body></html>")
        return "".join(html_parts)
    
    def _generate_custom_template(self, data: Dict[str, Any], template: str) -> str:
        """Generate custom HTML template from data."""
        # This can be extended with more template types
        return self._generate_default_template(data)
    
    async def upload_file(self, file: UploadFile, user_id: uuid.UUID) -> Dict[str, Any]:
        """Upload and store a file."""
        try:
            # Create user-specific directory
            user_dir = self.upload_dir / str(user_id)
            user_dir.mkdir(exist_ok=True)
            
            # Generate unique filename
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"{timestamp}_{file.filename}"
            file_path = user_dir / filename
            
            # Save file
            async with aiofiles.open(file_path, 'wb') as f:
                content = await file.read()
                await f.write(content)
            
            return {
                "success": True,
                "filename": filename,
                "original_name": file.filename,
                "size": len(content),
                "content_type": file.content_type,
                "path": str(file_path)
            }
        except Exception as e:
            logger.error(f"Error uploading file: {e}")
            return {"success": False, "error": str(e)}
    
    async def upload_content(self, filename: str, content: str, user_id: uuid.UUID) -> Dict[str, Any]:
        """Upload and store content as a file (for base64 data)."""
        try:
            # Create user-specific directory
            user_dir = self.upload_dir / str(user_id)
            user_dir.mkdir(exist_ok=True)
            
            file_path = user_dir / filename
            
            # Decode base64 content if it's base64
            try:
                # Try to decode as base64
                binary_content = base64.b64decode(content)
                mode = 'wb'
            except Exception:
                # If not base64, treat as text
                binary_content = content.encode('utf-8')
                mode = 'wb'
            
            # Save file
            async with aiofiles.open(file_path, mode) as f:
                await f.write(binary_content)
            
            return {
                "success": True,
                "filename": filename,
                "size": len(binary_content),
                "path": str(file_path)
            }
        except Exception as e:
            logger.error(f"Error uploading content: {e}")
            return {"success": False, "error": str(e)}
    
    async def download_file(self, filename: str, user_id: uuid.UUID) -> Dict[str, Any]:
        """Download a file by filename."""
        try:
            user_dir = self.upload_dir / str(user_id)
            file_path = user_dir / filename
            
            if not file_path.exists():
                return {"success": False, "error": "File not found"}
            
            async with aiofiles.open(file_path, 'rb') as f:
                content = await f.read()
            
            return {
                "success": True,
                "filename": filename,
                "content": base64.b64encode(content).decode(),
                "size": len(content)
            }
        except Exception as e:
            logger.error(f"Error downloading file: {e}")
            return {"success": False, "error": str(e)}
    
    async def list_user_files(self, user_id: uuid.UUID) -> Dict[str, Any]:
        """List all files for a user."""
        try:
            user_dir = self.upload_dir / str(user_id)
            if not user_dir.exists():
                return {"success": True, "files": []}
            
            files = []
            for file_path in user_dir.iterdir():
                if file_path.is_file():
                    stat = file_path.stat()
                    files.append({
                        "filename": file_path.name,
                        "size": stat.st_size,
                        "created": datetime.fromtimestamp(stat.st_ctime).isoformat(),
                        "modified": datetime.fromtimestamp(stat.st_mtime).isoformat()
                    })
            
            return {"success": True, "files": files}
        except Exception as e:
            logger.error(f"Error listing files: {e}")
            return {"success": False, "error": str(e)}
    
    async def delete_file(self, filename: str, user_id: uuid.UUID) -> Dict[str, Any]:
        """Delete a file."""
        try:
            user_dir = self.upload_dir / str(user_id)
            file_path = user_dir / filename
            
            if not file_path.exists():
                return {"success": False, "error": "File not found"}
            
            file_path.unlink()
            return {"success": True, "message": f"File {filename} deleted"}
        except Exception as e:
            logger.error(f"Error deleting file: {e}")
            return {"success": False, "error": str(e)}
    
    async def generate_qr_code(self, data: str, size: int = 10) -> Dict[str, Any]:
        """Generate QR code from data."""
        try:
            qr = qrcode.QRCode(version=1, box_size=size, border=5)
            qr.add_data(data)
            qr.make(fit=True)
            
            img = qr.make_image(fill_color="black", back_color="white")
            
            # Convert to base64
            buffer = io.BytesIO()
            img.save(buffer, format='PNG')
            img_data = buffer.getvalue()
            
            return {
                "success": True,
                "content": base64.b64encode(img_data).decode(),
                "size": len(img_data)
            }
        except Exception as e:
            logger.error(f"Error generating QR code: {e}")
            return {"success": False, "error": str(e)}
    
    async def convert_document(self, content: str, from_format: str, to_format: str) -> Dict[str, Any]:
        """Convert document between formats."""
        try:
            if from_format == "markdown" and to_format == "html":
                html_content = markdown.markdown(content)
                return {"success": True, "content": html_content, "format": "html"}
            elif from_format == "html" and to_format == "markdown":
                # Simple HTML to markdown conversion
                import re
                markdown_content = re.sub(r'<h1>(.*?)</h1>', r'# \1', content)
                markdown_content = re.sub(r'<h2>(.*?)</h2>', r'## \1', markdown_content)
                markdown_content = re.sub(r'<p>(.*?)</p>', r'\1\n\n', markdown_content)
                markdown_content = re.sub(r'<[^>]+>', '', markdown_content)
                return {"success": True, "content": markdown_content, "format": "markdown"}
            else:
                return {"success": False, "error": f"Unsupported conversion: {from_format} to {to_format}"}
        except Exception as e:
            logger.error(f"Error converting document: {e}")
            return {"success": False, "error": str(e)}


# Global file management service instance
file_management_service = FileManagementService() 