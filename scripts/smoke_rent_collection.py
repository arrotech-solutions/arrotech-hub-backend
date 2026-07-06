#!/usr/bin/env python3
"""Manual smoke checks for rent collection agent (run against local or prod API)."""
from __future__ import annotations

import argparse
import json
import os
import sys

import httpx


def main() -> int:
    parser = argparse.ArgumentParser(description="Rent collection readiness smoke test")
    parser.add_argument("--base-url", default=os.getenv("API_BASE_URL", "http://localhost:8000"))
    parser.add_argument("--token", default=os.getenv("AUTH_TOKEN", ""), help="Bearer JWT")
    parser.add_argument("--spreadsheet-id", default="", help="Optional spreadsheet ID for readiness")
    args = parser.parse_args()

    if not args.token:
        print("Set AUTH_TOKEN or pass --token", file=sys.stderr)
        return 1

    headers = {"Authorization": f"Bearer {args.token}"}
    params = {}
    if args.spreadsheet_id:
        params["spreadsheet_id"] = args.spreadsheet_id

    url = f"{args.base_url.rstrip('/')}/api/rent-collection/readiness"
    with httpx.Client(timeout=30.0) as client:
        res = client.get(url, headers=headers, params=params)
        print(f"GET {url} -> {res.status_code}")
        try:
            payload = res.json()
        except Exception:
            print(res.text)
            return 1
        print(json.dumps(payload, indent=2))
        if res.status_code != 200:
            return 1
        data = (payload or {}).get("data") or {}
        print("\nSummary:")
        print(f"  WhatsApp connected: {data.get('whatsapp_connected')}")
        print(f"  Rent workflow active: {data.get('rent_workflow_active')}")
        print(f"  M-Pesa mode: {data.get('mpesa_mode')}")
        print(f"  Tenant count: {data.get('tenant_count')}")
        print(f"  Ready: {data.get('ready')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
