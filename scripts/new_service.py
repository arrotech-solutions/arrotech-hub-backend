#!/usr/bin/env python3
"""
Service Scaffolding Generator — Development Harness

Generates boilerplate for new integrations following established patterns.

Usage:
    python scripts/new_service.py stripe
    python scripts/new_service.py my_platform --with-router --with-tools

Generates:
    src/services/<name>_service.py
    src/routers/<name>_router.py (if --with-router)
    tests/test_<name>_service.py
"""

import os
import sys
from datetime import datetime
from pathlib import Path
from textwrap import dedent

PROJECT_ROOT = Path(__file__).parent.parent
SRC_DIR = PROJECT_ROOT / "src"


def generate_service(name: str) -> str:
    class_name = "".join(w.capitalize() for w in name.split("_")) + "Service"
    return dedent(f'''\
    """
    {class_name} — {name.replace("_", " ").title()} integration service.

    Created: {datetime.now().strftime("%Y-%m-%d")}

    Follows the service patterns defined in src/services/AGENTS.md:
    - Receives AsyncSession via parameter injection
    - Uses logger (not print) for all output
    - Wraps external API calls in try/except with error classification
    - Tool methods return dict with "success" and "data"/"error" keys
    """

    import logging
    from typing import Any, Dict, Optional

    from sqlalchemy.ext.asyncio import AsyncSession

    logger = logging.getLogger(__name__)


    class {class_name}:
        """Service for {name.replace("_", " ").title()} integration."""

        def __init__(self, db: AsyncSession, user: Any):
            self.db = db
            self.user = user

        async def health_check(self) -> Dict[str, Any]:
            """Check connectivity to the {name.replace("_", " ").title()} API."""
            try:
                # TODO: Implement actual health check
                return {{"success": True, "data": {{"status": "connected"}}}}
            except Exception as e:
                logger.error(f"{class_name} health check failed: {{e}}")
                return {{"success": False, "error": str(e)}}

        async def list_items(self, **kwargs) -> Dict[str, Any]:
            """List items from {name.replace("_", " ").title()}."""
            try:
                # TODO: Implement list operation
                logger.info(f"Listing items for user {{self.user.id}}")
                return {{"success": True, "data": {{"items": []}}}}
            except Exception as e:
                logger.error(f"Failed to list items: {{e}}")
                return {{"success": False, "error": str(e)}}

        async def get_item(self, item_id: str) -> Dict[str, Any]:
            """Get a single item by ID."""
            try:
                # TODO: Implement get operation
                logger.info(f"Getting item {{item_id}}")
                return {{"success": True, "data": {{"item_id": item_id}}}}
            except Exception as e:
                logger.error(f"Failed to get item: {{e}}")
                return {{"success": False, "error": str(e)}}

        async def create_item(self, **kwargs) -> Dict[str, Any]:
            """Create a new item."""
            try:
                # TODO: Implement create operation
                logger.info(f"Creating item with args: {{kwargs}}")
                return {{"success": True, "data": {{"created": True}}}}
            except Exception as e:
                logger.error(f"Failed to create item: {{e}}")
                return {{"success": False, "error": str(e)}}
    ''')


def generate_router(name: str) -> str:
    class_name = "".join(w.capitalize() for w in name.split("_"))
    service_class = class_name + "Service"
    return dedent(f'''\
    """
    {class_name} Router — HTTP endpoints for {name.replace("_", " ").title()} integration.

    Created: {datetime.now().strftime("%Y-%m-%d")}

    Thin router layer — delegates all logic to {service_class}.
    """

    import logging
    from typing import Any, Dict

    from fastapi import APIRouter, Depends
    from sqlalchemy.ext.asyncio import AsyncSession

    from ..database import get_db

    logger = logging.getLogger(__name__)

    router = APIRouter(
        prefix="/{name.replace("_", "-")}",
        tags=["{name.replace("_", " ").title()}"],
    )


    @router.get("/health")
    async def {name}_health(db: AsyncSession = Depends(get_db)):
        """Health check for {name.replace("_", " ").title()} integration."""
        return {{"status": "ok", "service": "{name}"}}
    ''')


def generate_test(name: str) -> str:
    class_name = "".join(w.capitalize() for w in name.split("_")) + "Service"
    return dedent(f'''\
    """
    Tests for {class_name}.

    Created: {datetime.now().strftime("%Y-%m-%d")}
    """

    import pytest


    class Test{class_name}:
        """Test suite for {class_name}."""

        def test_service_import(self):
            """Verify the service module can be imported."""
            from src.services.{name}_service import {class_name}
            assert {class_name} is not None

        @pytest.mark.asyncio
        async def test_health_check(self, db_session, test_user):
            """Test the health check method."""
            from src.services.{name}_service import {class_name}
            service = {class_name}(db=db_session, user=test_user)
            result = await service.health_check()
            assert isinstance(result, dict)
            assert "success" in result

        @pytest.mark.asyncio
        async def test_list_items(self, db_session, test_user):
            """Test listing items."""
            from src.services.{name}_service import {class_name}
            service = {class_name}(db=db_session, user=test_user)
            result = await service.list_items()
            assert result["success"] is True

        @pytest.mark.asyncio
        async def test_get_item(self, db_session, test_user):
            """Test getting a single item."""
            from src.services.{name}_service import {class_name}
            service = {class_name}(db=db_session, user=test_user)
            result = await service.get_item(item_id="test-123")
            assert isinstance(result, dict)
    ''')


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/new_service.py <platform_name> [--with-router] [--with-tools]")
        print("Example: python scripts/new_service.py stripe --with-router")
        sys.exit(1)

    name = sys.argv[1].lower().replace("-", "_")
    with_router = "--with-router" in sys.argv
    with_tools = "--with-tools" in sys.argv

    print(f"Scaffolding new service: {name}")
    print("=" * 50)

    created = []

    # Service file
    service_path = SRC_DIR / "services" / f"{name}_service.py"
    if service_path.exists():
        print(f"  SKIP: {service_path.relative_to(PROJECT_ROOT)} (already exists)")
    else:
        service_path.write_text(generate_service(name), encoding="utf-8")
        created.append(str(service_path.relative_to(PROJECT_ROOT)))
        print(f"  CREATED: {service_path.relative_to(PROJECT_ROOT)}")

    # Router file
    if with_router:
        router_path = SRC_DIR / "routers" / f"{name}_router.py"
        if router_path.exists():
            print(f"  SKIP: {router_path.relative_to(PROJECT_ROOT)} (already exists)")
        else:
            router_path.write_text(generate_router(name), encoding="utf-8")
            created.append(str(router_path.relative_to(PROJECT_ROOT)))
            print(f"  CREATED: {router_path.relative_to(PROJECT_ROOT)}")

    # Test file
    test_path = PROJECT_ROOT / "tests" / f"test_{name}_service.py"
    if test_path.exists():
        print(f"  SKIP: {test_path.relative_to(PROJECT_ROOT)} (already exists)")
    else:
        test_path.write_text(generate_test(name), encoding="utf-8")
        created.append(str(test_path.relative_to(PROJECT_ROOT)))
        print(f"  CREATED: {test_path.relative_to(PROJECT_ROOT)}")

    # Print TODO checklist
    print(f"\n{'=' * 50}")
    print("TODO Checklist:")
    print(f"  [ ] Implement service methods in {name}_service.py")
    if with_router:
        print(f"  [ ] Add endpoints to {name}_router.py")
        print(f"  [ ] Register router in src/routers/__init__.py")
    if with_tools:
        print(f"  [ ] Add tool schemas to src/services/platform_registry.py")
        print(f"  [ ] Add tool availability to src/services/dynamic_tool_registry.py")
        print(f"  [ ] Add dispatch entries to src/services/tool_executor.py")
    print(f"  [ ] Run: python scripts/verify_architecture.py")
    print(f"  [ ] Run: pytest tests/test_{name}_service.py -v")
    print(f"  [ ] Update AGENTS.md if new patterns introduced")
    print(f"{'=' * 50}")


if __name__ == "__main__":
    main()
