"""
Inventory Management Service for Arrotech Hub.

Stateless processing tools for product catalog and stock management.
No database models — data flows through workflow variables.
Supports food/meat (kg, cuts), clothing (size, color), and retail goods.
Users connect their own databases (Airtable, Google Sheets, etc.) for persistence.
"""

import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


PRODUCT_CATEGORIES = [
    "food", "meat", "poultry", "seafood", "vegetables", "beverages",
    "clothing", "footwear", "accessories",
    "electronics", "appliances",
    "grocery", "household", "beauty",
    "pharmacy", "health",
    "stationery", "hardware",
    "custom",
]

UNIT_TYPES = ["pcs", "kg", "g", "lb", "oz", "ltr", "ml", "pack", "box", "dozen", "pair", "set"]

CLOTHING_SIZES = ["XS", "S", "M", "L", "XL", "XXL", "3XL", "4XL"]

MEAT_CUTS = [
    "whole", "fillet", "ribeye", "sirloin", "t-bone", "tenderloin",
    "mince", "ribs", "chops", "steak", "brisket", "shank",
    "thigh", "breast", "drumstick", "wings",  # Poultry
]


class InventoryService:
    """Stateless inventory processing tools for workflow building blocks."""

    def __init__(self):
        pass

    async def handle_operation(
        self,
        operation: str,
        **kwargs
    ) -> Dict[str, Any]:
        """Route to the appropriate inventory tool."""
        try:
            kwargs = self._coerce_types(kwargs)

            if operation == "create_product":
                return await self.create_product(**kwargs)
            elif operation == "list_products":
                return await self.list_products(**kwargs)
            elif operation == "update_stock":
                return await self.update_stock(**kwargs)
            elif operation == "get_product_by_category":
                return await self.get_product_by_category(**kwargs)
            elif operation == "check_stock_availability":
                return await self.check_stock_availability(**kwargs)
            elif operation == "search_products":
                return await self.search_products(**kwargs)
            else:
                return {"success": False, "error": f"Unknown operation: {operation}"}
        except Exception as e:
            logger.error(f"Inventory service error ({operation}): {e}")
            return {"success": False, "error": str(e)}

    @staticmethod
    def _coerce_types(kwargs: Dict[str, Any]) -> Dict[str, Any]:
        """Coerce string values from workflow variables to proper types."""
        float_fields = {
            "price", "cost_price", "weight", "min_price", "max_price",
            "quantity_change", "requested_quantity", "current_stock",
            "min_stock", "max_stock", "weight_per_unit",
        }
        int_fields = {"max_results", "limit", "reorder_level"}

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
    # 1. CREATE PRODUCT
    # ──────────────────────────────────────────────────────────────

    async def create_product(
        self,
        name: str = "",
        category: str = "custom",
        price: float = 0.0,
        cost_price: float = 0.0,
        description: str = "",
        unit_type: str = "pcs",
        sku: str = "",
        barcode: str = "",
        current_stock: float = 0,
        reorder_level: int = 0,
        # Clothing-specific
        sizes: List[str] = None,
        colors: List[str] = None,
        material: str = "",
        # Meat/Food-specific
        cuts: List[str] = None,
        weight_per_unit: float = 0.0,
        weight_based_pricing: bool = False,
        # General variants
        variants: List[Dict[str, Any]] = None,
        currency: str = "KES",
        images: List[str] = None,
        tags: List[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Create a structured product entry supporting multiple industries.

        Examples:
        - Meat: create_product(name="Ribeye Steak", category="meat", price=1500, unit_type="kg", cuts=["ribeye"])
        - Clothing: create_product(name="Cotton T-Shirt", category="clothing", price=800, sizes=["S","M","L"], colors=["Black","White"])
        - Retail: create_product(name="USB Cable", category="electronics", price=250, sku="USB-001", current_stock=50)
        """
        if not name:
            return {"success": False, "error": "Product name is required"}
        if price <= 0:
            return {"success": False, "error": "Price must be greater than 0"}

        # Validate unit type
        if unit_type not in UNIT_TYPES:
            unit_type = "pcs"

        # Generate product ID and SKU
        now = datetime.now()
        product_id = f"PRD-{uuid.uuid4().hex[:8].upper()}"
        if not sku:
            category_prefix = category[:3].upper() if category else "GEN"
            sku = f"{category_prefix}-{uuid.uuid4().hex[:6].upper()}"

        # Build product object
        product = {
            "product_id": product_id,
            "name": name,
            "description": description,
            "category": category,
            "sku": sku,
            "barcode": barcode,
            "price": round(price, 2),
            "cost_price": round(cost_price, 2) if cost_price else None,
            "currency": currency,
            "unit_type": unit_type,
            "current_stock": current_stock,
            "reorder_level": reorder_level,
            "in_stock": current_stock > 0,
            "images": images or [],
            "tags": tags or [],
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
        }

        # Add industry-specific fields
        if category in ("clothing", "footwear", "accessories"):
            product["variants_type"] = "clothing"
            product["sizes"] = sizes or []
            product["colors"] = colors or []
            product["material"] = material

            # Generate variant combinations
            if sizes and colors:
                variant_list = []
                for size in sizes:
                    for color in colors:
                        variant_list.append({
                            "variant_id": f"{sku}-{size}-{color[:3].upper()}",
                            "size": size,
                            "color": color,
                            "price": price,
                            "stock": 0,
                        })
                product["generated_variants"] = variant_list
                product["variant_count"] = len(variant_list)

        elif category in ("meat", "poultry", "seafood"):
            product["variants_type"] = "meat"
            product["cuts"] = cuts or []
            product["weight_per_unit"] = weight_per_unit
            product["weight_based_pricing"] = weight_based_pricing
            if weight_based_pricing:
                product["price_label"] = f"{currency} {price:,.0f}/kg"

        elif variants:
            # Custom variants
            product["variants_type"] = "custom"
            product["custom_variants"] = variants

        # Calculate profit margin
        if cost_price and cost_price > 0:
            margin = ((price - cost_price) / price) * 100
            product["profit_margin"] = round(margin, 1)

        price_label = f"{currency} {price:,.0f}"
        if unit_type == "kg":
            price_label += "/kg"

        return {
            "success": True,
            "product": product,
            "product_id": product_id,
            "sku": sku,
            "message": f"✅ Product created: {name} — {price_label} (SKU: {sku})",
        }

    # ──────────────────────────────────────────────────────────────
    # 2. LIST PRODUCTS
    # ──────────────────────────────────────────────────────────────

    async def list_products(
        self,
        category: str = "",
        in_stock: Optional[bool] = None,
        min_price: float = 0,
        max_price: float = 0,
        sort_by: str = "name",
        sort_order: str = "asc",
        limit: int = 20,
        tags: List[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Build a structured query/filter for listing products.
        Returns a filter specification for the user's connected database.
        """
        filters = {}

        if category:
            filters["category"] = category
        if in_stock is not None:
            filters["in_stock"] = in_stock
        if min_price > 0:
            filters["min_price"] = min_price
        if max_price > 0:
            filters["max_price"] = max_price
        if tags:
            filters["tags"] = tags

        # Build description
        parts = []
        if category:
            parts.append(f"category='{category}'")
        if in_stock is not None:
            parts.append(f"in_stock={in_stock}")
        if min_price > 0:
            parts.append(f"min_price={min_price}")
        if max_price > 0:
            parts.append(f"max_price={max_price}")
        if tags:
            parts.append(f"tags={tags}")

        filter_description = ", ".join(parts) if parts else "all products"

        return {
            "success": True,
            "filters": filters,
            "limit": min(limit, 100),
            "sort_by": sort_by,
            "sort_order": sort_order,
            "filter_description": filter_description,
            "message": f"Query built for products: {filter_description} (limit: {min(limit, 100)}, sort: {sort_by} {sort_order})",
            "note": "Connect a database (Airtable, Google Sheets, or custom DB) to execute this query against your product catalog.",
        }

    # ──────────────────────────────────────────────────────────────
    # 3. UPDATE STOCK
    # ──────────────────────────────────────────────────────────────

    async def update_stock(
        self,
        product_id: str = "",
        product_name: str = "",
        quantity_change: float = 0,
        operation: str = "add",
        current_stock: float = 0,
        reason: str = "",
        variant_id: str = "",
        **kwargs
    ) -> Dict[str, Any]:
        """
        Update stock levels for a product.

        operation: "set" (absolute), "add" (increment), "subtract" (decrement)
        """
        if not product_id and not product_name:
            return {"success": False, "error": "Product ID or product name is required"}

        identifier = product_id or product_name

        if operation not in ("set", "add", "subtract"):
            return {"success": False, "error": f"Invalid operation: '{operation}'. Use 'set', 'add', or 'subtract'."}

        # Calculate new stock
        if operation == "set":
            new_stock = quantity_change
        elif operation == "add":
            new_stock = current_stock + quantity_change
        elif operation == "subtract":
            new_stock = current_stock - quantity_change
            if new_stock < 0:
                return {
                    "success": False,
                    "error": f"Insufficient stock. Current: {current_stock}, requested deduction: {quantity_change}",
                    "current_stock": current_stock,
                    "requested": quantity_change,
                }

        now = datetime.now()

        stock_update = {
            "product_id": product_id,
            "product_name": product_name,
            "operation": operation,
            "previous_stock": current_stock,
            "quantity_change": quantity_change,
            "new_stock": round(new_stock, 2),
            "in_stock": new_stock > 0,
            "variant_id": variant_id or None,
            "reason": reason,
            "updated_at": now.isoformat(),
        }

        # Low stock warning
        low_stock_warning = None
        if 0 < new_stock <= 5:
            low_stock_warning = f"⚠️ Low stock alert: only {new_stock} remaining"

        op_icon = {"set": "🔄", "add": "📦", "subtract": "📤"}.get(operation, "📋")

        return {
            "success": True,
            "stock_update": stock_update,
            "product_id": product_id,
            "new_stock": round(new_stock, 2),
            "in_stock": new_stock > 0,
            "low_stock_warning": low_stock_warning,
            "message": f"{op_icon} Stock updated for '{identifier}': {current_stock} → {new_stock} ({operation} {quantity_change})",
        }

    # ──────────────────────────────────────────────────────────────
    # 4. GET PRODUCT BY CATEGORY
    # ──────────────────────────────────────────────────────────────

    async def get_product_by_category(
        self,
        category: str = "",
        include_out_of_stock: bool = False,
        sort_by: str = "name",
        limit: int = 20,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Build a query to get products by category.
        Returns filter specification for the user's connected database.
        """
        if not category:
            return {"success": False, "error": "Category is required"}

        filters = {
            "category": category,
        }
        if not include_out_of_stock:
            filters["in_stock"] = True

        # Provide category-specific hints
        category_hints = {
            "meat": {"suggested_fields": ["name", "cuts", "weight_per_unit", "price", "unit_type"]},
            "poultry": {"suggested_fields": ["name", "cuts", "weight_per_unit", "price", "unit_type"]},
            "clothing": {"suggested_fields": ["name", "sizes", "colors", "material", "price"]},
            "footwear": {"suggested_fields": ["name", "sizes", "colors", "price"]},
            "electronics": {"suggested_fields": ["name", "sku", "price", "current_stock"]},
        }

        hints = category_hints.get(category, {"suggested_fields": ["name", "price", "current_stock"]})

        stock_text = "including out-of-stock" if include_out_of_stock else "in-stock only"

        return {
            "success": True,
            "filters": filters,
            "limit": min(limit, 100),
            "sort_by": sort_by,
            "category": category,
            "hints": hints,
            "message": f"Query built for '{category}' products ({stock_text}, limit: {min(limit, 100)})",
            "note": "Connect a database to execute this query against your product catalog.",
        }

    # ──────────────────────────────────────────────────────────────
    # 5. CHECK STOCK AVAILABILITY
    # ──────────────────────────────────────────────────────────────

    async def check_stock_availability(
        self,
        product_id: str = "",
        product_name: str = "",
        requested_quantity: float = 1,
        current_stock: float = 0,
        variant_id: str = "",
        unit_type: str = "pcs",
        **kwargs
    ) -> Dict[str, Any]:
        """
        Check if a product can fulfill a requested quantity.
        """
        if not product_id and not product_name:
            return {"success": False, "error": "Product ID or product name is required"}

        identifier = product_id or product_name

        is_available = current_stock >= requested_quantity
        shortfall = max(0, requested_quantity - current_stock)

        if is_available:
            remaining_after = current_stock - requested_quantity
            message = f"✅ '{identifier}' is available: {requested_quantity} {unit_type} requested, {current_stock} {unit_type} in stock ({remaining_after} remaining after fulfillment)"
        else:
            message = f"❌ '{identifier}' insufficient stock: {requested_quantity} {unit_type} requested, only {current_stock} {unit_type} available (short by {shortfall})"

        return {
            "success": True,
            "is_available": is_available,
            "product_id": product_id,
            "product_name": product_name,
            "requested_quantity": requested_quantity,
            "current_stock": current_stock,
            "shortfall": shortfall,
            "remaining_after_fulfillment": max(0, current_stock - requested_quantity) if is_available else 0,
            "variant_id": variant_id or None,
            "unit_type": unit_type,
            "message": message,
        }

    # ──────────────────────────────────────────────────────────────
    # 6. SEARCH PRODUCTS
    # ──────────────────────────────────────────────────────────────

    async def search_products(
        self,
        query: str = "",
        category: str = "",
        in_stock: Optional[bool] = None,
        max_results: int = 10,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Build a search query for products by name/description.
        Returns a search specification for the user's connected database.
        """
        if not query:
            return {"success": False, "error": "Search query is required"}

        search_spec = {
            "query": query,
            "search_fields": ["name", "description", "tags", "sku", "barcode"],
            "max_results": min(max_results, 50),
        }

        if category:
            search_spec["category_filter"] = category
        if in_stock is not None:
            search_spec["in_stock_filter"] = in_stock

        filter_parts = [f"query='{query}'"]
        if category:
            filter_parts.append(f"category='{category}'")
        if in_stock is not None:
            filter_parts.append(f"in_stock={in_stock}")

        return {
            "success": True,
            "search_spec": search_spec,
            "query": query,
            "filter_description": ", ".join(filter_parts),
            "message": f"🔍 Search query built: '{query}' ({', '.join(filter_parts[1:])})" if len(filter_parts) > 1 else f"🔍 Search query built: '{query}'",
            "note": "Connect a database to execute this search against your product catalog.",
        }


# Global instance
inventory_service = InventoryService()
