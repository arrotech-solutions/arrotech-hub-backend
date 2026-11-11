"""Tests for Bruno workspace generation helpers."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_ensure_generation_env_sets_testing_defaults(monkeypatch):
    monkeypatch.delenv("TESTING", raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    from scripts.bruno_openapi import ensure_generation_env

    ensure_generation_env()
    assert os.environ.get("TESTING") == "1"
    assert os.environ.get("ENVIRONMENT") in {"testing", "development", "test"}


def test_dump_openapi_writes_paths(tmp_path, monkeypatch):
    from fastapi import FastAPI

    tiny = FastAPI()

    @tiny.get("/health")
    def health():
        return {"ok": True}

    @tiny.post("/auth/login")
    def login():
        return {"ok": True}

    monkeypatch.setattr("scripts.bruno_openapi.load_app", lambda: tiny)
    from scripts.bruno_openapi import dump_openapi

    out = tmp_path / "openapi.json"
    spec = dump_openapi(out)
    assert out.is_file()
    assert "/health" in spec["paths"]
    assert "/auth/login" in spec["paths"]
