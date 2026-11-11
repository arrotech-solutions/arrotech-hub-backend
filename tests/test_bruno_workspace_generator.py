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


def test_write_workspace_scaffold_envs(tmp_path):
    from scripts.bruno_workspace_patch import write_workspace_scaffold

    write_workspace_scaffold(tmp_path)
    assert (tmp_path / "workspace.yml").is_file()
    local = (tmp_path / "environments" / "Local.yml").read_text(encoding="utf-8")
    prod = (tmp_path / "environments" / "Production.yml").read_text(encoding="utf-8")
    assert "http://localhost:8000" in local
    assert "https://prod.api.arrotechsolutions.com" in prod
    assert "email" in local and "password" in local
    workspace = (tmp_path / "workspace.yml").read_text(encoding="utf-8")
    assert "collections/arrotech-hub-api" in workspace


def test_patch_collection_rewrites_hardcoded_host(tmp_path):
    from scripts.bruno_workspace_patch import patch_collection_base_url

    collection = tmp_path / "collections" / "arrotech-hub-api"
    auth_dir = collection / "auth"
    auth_dir.mkdir(parents=True)
    me = auth_dir / "me.yml"
    me.write_text(
        "url: http://localhost:8000/auth/me\nmethod: GET\n",
        encoding="utf-8",
    )
    (collection / "opencollection.yml").write_text(
        "opencollection: 1.0.0\ninfo:\n  name: Arrotech Hub API\n",
        encoding="utf-8",
    )
    n = patch_collection_base_url(collection)
    assert n >= 1
    text = me.read_text(encoding="utf-8")
    assert "{{baseUrl}}" in text
    assert "http://localhost:8000" not in text


def test_write_readme_if_missing_preserves_existing(tmp_path):
    from scripts.bruno_workspace_patch import write_readme_if_missing

    (tmp_path / "README.md").write_text("KEEP\n", encoding="utf-8")
    write_readme_if_missing(tmp_path)
    assert (tmp_path / "README.md").read_text(encoding="utf-8") == "KEEP\n"
