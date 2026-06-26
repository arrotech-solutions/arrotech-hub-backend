"""
Product vision extraction for the Catalog Builder.

Takes one or more photos of a single product (multiple angles) and asks an
OpenAI multimodal model (gpt-4o) to return structured product details that can
be written into a Google Sheet the WhatsApp ordering agent's RAG understands.

Key resolution mirrors coding_agent_llm.py: system OPENAI_API_KEY first, then
the user's BYOK key from UserSettings. Price is returned as a non-binding
estimate that the user must confirm in the review step.
"""

import base64
import json
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings

logger = logging.getLogger(__name__)

# Cap images per product to keep token cost predictable.
MAX_IMAGES_PER_PRODUCT = 6

_SUPPORTED_IMAGE_MIME = {
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/webp",
    "image/gif",
}

_EXTRACTION_SYSTEM_PROMPT = (
    "You are a product cataloguing assistant for an e-commerce business. "
    "You are shown one or more photos of a SINGLE physical product (possibly "
    "from different angles). Identify the product and return concise, accurate, "
    "sellable catalog details. Only describe what is visible or strongly implied "
    "by the photos; never invent specifications you cannot see. If you are unsure "
    "of a field, leave it empty rather than guessing. Prices are rough market "
    "estimates only."
)


def _build_extraction_instruction(currency: str, hint: Optional[str]) -> str:
    instruction = (
        "You may receive several photos of the SAME product from different angles. "
        "Combine visible details from ALL angles — labels, ports, specs, colour, model "
        "numbers, packaging text, etc. — into one coherent listing.\n\n"
        "Analyse the product photo(s) and return a JSON object with EXACTLY these keys:\n"
        '  "name": short retail product name (string),\n'
        '  "category": product category, e.g. Electronics, Gaming, Audio (string),\n'
        '  "brand": brand/manufacturer if visible, else "" (string),\n'
        '  "description": 1-2 sentence sales description of visible features (string),\n'
        '  "specs": notable visible specs/attributes such as colour, model, '
        "connectivity (string, comma-separated, may be empty),\n"
        '  "suggested_sku": a short uppercase SKU you propose, e.g. "HEADSET-001" (string),\n'
        f'  "price_estimate": rough market price as a number in {currency} with NO '
        "currency symbol, or null if you cannot estimate (number or null),\n"
        '  "confidence": your confidence the identification is correct, 0.0-1.0 (number).\n'
        "Return ONLY the JSON object, no markdown, no commentary."
    )
    if hint:
        instruction += f"\n\nSeller hint about this product: {hint.strip()}"
    return instruction


class ProductVisionService:
    """Extract structured product data from photos via OpenAI vision."""

    def __init__(self):
        self.model = getattr(settings, "OPENAI_MODEL", "gpt-4o") or "gpt-4o"

    async def _resolve_api_key(
        self, user_id: Optional[Any], db: Optional[AsyncSession]
    ) -> Optional[str]:
        """System key first, then per-user BYOK key (mirror coding_agent_llm)."""
        api_key = getattr(settings, "OPENAI_API_KEY", "") or ""
        if user_id is None or db is None:
            return api_key or None
        try:
            from ..models import UserSettings

            result = await db.execute(
                select(UserSettings).where(UserSettings.user_id == user_id)
            )
            user_settings = result.scalar_one_or_none()
            if user_settings and user_settings.openai_api_key:
                api_key = user_settings.openai_api_key
        except Exception as e:
            logger.warning(f"[PRODUCT_VISION] BYOK lookup failed (continuing): {e}")
        return api_key or None

    async def extract_product(
        self,
        images: List[bytes],
        mime_types: List[str],
        currency: str = "KES",
        hint: Optional[str] = None,
        user_id: Optional[Any] = None,
        db: Optional[AsyncSession] = None,
    ) -> Dict[str, Any]:
        """
        Returns { success, product: {...}, error? }.

        `images` and `mime_types` are parallel lists describing the same product.
        """
        if not images:
            return {"success": False, "error": "No images provided"}

        api_key = await self._resolve_api_key(user_id, db)
        if not api_key:
            return {
                "success": False,
                "error": "No OpenAI API key configured. Add one in Settings or contact support.",
            }

        # Build multimodal content: instruction text + up to N image parts.
        content: List[Dict[str, Any]] = [
            {"type": "text", "text": _build_extraction_instruction(currency, hint)}
        ]
        used = 0
        for img_bytes, mime in zip(images, mime_types):
            if used >= MAX_IMAGES_PER_PRODUCT:
                break
            if not img_bytes:
                continue
            mime_norm = (mime or "image/jpeg").split(";")[0].strip().lower()
            if mime_norm not in _SUPPORTED_IMAGE_MIME:
                # Default unknown types to jpeg; the API is tolerant of the label.
                mime_norm = "image/jpeg"
            b64 = base64.b64encode(img_bytes).decode("ascii")
            content.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{mime_norm};base64,{b64}",
                        "detail": "low",
                    },
                }
            )
            used += 1

        if used == 0:
            return {"success": False, "error": "No valid images provided"}

        try:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(api_key=api_key)
            response = await client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": _EXTRACTION_SYSTEM_PROMPT},
                    {"role": "user", "content": content},
                ],
                temperature=0.2,
                max_tokens=600,
                response_format={"type": "json_object"},
            )
            raw = (response.choices[0].message.content or "").strip()
            product = self._parse_product_json(raw)
            return {"success": True, "product": product}
        except Exception as e:
            logger.error(f"[PRODUCT_VISION] Extraction failed: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    @staticmethod
    def _parse_product_json(raw: str) -> Dict[str, Any]:
        """Parse and normalise the model's JSON into a stable product dict."""
        data: Dict[str, Any] = {}
        if raw:
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                # Best-effort: strip code fences / extract the first {...} block.
                cleaned = raw.strip().strip("`")
                start = cleaned.find("{")
                end = cleaned.rfind("}")
                if start != -1 and end != -1 and end > start:
                    try:
                        data = json.loads(cleaned[start : end + 1])
                    except json.JSONDecodeError:
                        data = {}

        def _s(value: Any) -> str:
            if value is None:
                return ""
            return str(value).strip()

        price_raw = data.get("price_estimate")
        price_estimate: Optional[float] = None
        if price_raw not in (None, "", "null"):
            try:
                price_estimate = round(float(str(price_raw).replace(",", "").strip()), 2)
            except (ValueError, TypeError):
                price_estimate = None

        confidence_raw = data.get("confidence")
        confidence: Optional[float] = None
        if confidence_raw not in (None, ""):
            try:
                confidence = max(0.0, min(1.0, float(confidence_raw)))
            except (ValueError, TypeError):
                confidence = None

        return {
            "name": _s(data.get("name")),
            "category": _s(data.get("category")),
            "brand": _s(data.get("brand")),
            "description": _s(data.get("description")),
            "specs": _s(data.get("specs")),
            "suggested_sku": _s(data.get("suggested_sku")),
            "price_estimate": price_estimate,
            "confidence": confidence,
        }


product_vision_service = ProductVisionService()
