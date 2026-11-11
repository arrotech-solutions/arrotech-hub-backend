"""Dump FastAPI OpenAPI JSON for Bruno workspace generation."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def ensure_generation_env() -> None:
    """Set safe env stubs so importing the app does not need live infra."""
    os.environ["TESTING"] = "1"

    env = os.environ.get("ENVIRONMENT", "").strip().lower()
    if env not in {"testing", "development", "test"}:
        os.environ["ENVIRONMENT"] = "testing"

    os.environ.setdefault("SECRET_KEY", "bruno-gen-secret-key-not-for-production")
    os.environ.setdefault("JWT_SECRET_KEY", "bruno-gen-jwt-secret-not-for-production")
    os.environ.setdefault(
        "DATABASE_URL", "postgresql://minihub:minihub@localhost:5432/minihub"
    )
    os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
    os.environ.setdefault("OPENAI_API_KEY", "sk-bruno-gen-placeholder")


def load_app():
    """Import and return the FastAPI application (after env stubs)."""
    ensure_generation_env()
    from src.main import app

    return app


def dump_openapi(path: Path) -> dict[str, Any]:
    """Write OpenAPI schema from the app to ``path`` and return the dict."""
    ensure_generation_env()
    app = load_app()
    spec = app.openapi()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(spec, indent=2) + "\n", encoding="utf-8")
    return spec
