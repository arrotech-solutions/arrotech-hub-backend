#!/usr/bin/env python3
"""
Validate product catalog rows for a Knowledge Base.

Checks sheet sources for missing images, duplicate names, and alt-text mismatches.

Usage:
    python scripts/validate_product_kb.py --kb-id <uuid> --user-id <uuid>

Requires DATABASE_URL and Google Sheets credentials configured for the user.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import select  # noqa: E402

from src.database import get_session_maker  # noqa: E402
from src.models import User  # noqa: E402
from src.services.product_catalog_service import ProductCatalogService  # noqa: E402


async def run(kb_id: str, user_id: str) -> int:
    session_maker = get_session_maker()
    async with session_maker() as session:
        user_result = await session.execute(
            select(User).filter(User.id == uuid.UUID(user_id))
        )
        user = user_result.scalars().first()
        if not user:
            print(f"User {user_id} not found", file=sys.stderr)
            return 1

        report = await ProductCatalogService.validate_kb_catalog(
            kb_id=kb_id, user=user, db=session
        )

    print(f"KB: {report.get('kb_id')}")
    print(f"Total products: {report.get('total_products', 0)}")
    print(f"Issues: {report.get('issue_count', 0)}")
    print(f"Healthy: {report.get('healthy')}")

    for issue in report.get("issues", []):
        print(f"  - [{issue.get('type')}] {issue.get('product_name')} (row {issue.get('row_index')})")

    return 0 if report.get("healthy") else 2


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate KB product catalog")
    parser.add_argument("--kb-id", required=True, help="Knowledge base UUID")
    parser.add_argument("--user-id", required=True, help="Owner user UUID")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run(args.kb_id, args.user_id)))


if __name__ == "__main__":
    main()
