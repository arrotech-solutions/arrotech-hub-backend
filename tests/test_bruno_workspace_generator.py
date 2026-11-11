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


def test_generate_invokes_import_and_patch(tmp_path, monkeypatch):
    calls: dict = {}

    def fake_dump(path):
        Path(path).write_text("{}", encoding="utf-8")
        return {"openapi": "3.0.0", "paths": {}}

    def fake_import(openapi_path, output_dir, collection_name="Arrotech Hub API"):
        calls["import"] = True
        coll = Path(output_dir) / "arrotech-hub-api"
        coll.mkdir(parents=True, exist_ok=True)
        (coll / "opencollection.yml").write_text(
            "opencollection: 1.0.0\ninfo:\n  name: Arrotech Hub API\n",
            encoding="utf-8",
        )

    monkeypatch.setattr("scripts.generate_bruno_workspace.dump_openapi", fake_dump)
    monkeypatch.setattr("scripts.generate_bruno_workspace.run_bruno_import", fake_import)
    monkeypatch.setattr(
        "scripts.generate_bruno_workspace.patch_collection_base_url",
        lambda d: calls.setdefault("patch", 1) or 1,
    )
    monkeypatch.setattr(
        "scripts.generate_bruno_workspace.write_workspace_scaffold",
        lambda r: calls.setdefault("scaffold", True),
    )
    monkeypatch.setattr(
        "scripts.generate_bruno_workspace.write_readme_if_missing",
        lambda r: calls.setdefault("readme", True),
    )
    from scripts.generate_bruno_workspace import generate

    generate(tmp_path)
    assert calls.get("import") and calls.get("patch") and calls.get("scaffold") and calls.get("readme")


def test_run_bruno_import_writes_bru_collection(tmp_path):
    from scripts.generate_bruno_workspace import run_bruno_import

    openapi = tmp_path / "openapi.json"
    openapi.write_text(
        """
        {
          "openapi": "3.0.3",
          "info": {"title": "t", "version": "1"},
          "paths": {
            "/health": {"get": {"tags": ["root"], "summary": "Health"}},
            "/auth/login": {"post": {"tags": ["auth"], "summary": "Login"}}
          }
        }
        """,
        encoding="utf-8",
    )
    out = tmp_path / "collections"
    out.mkdir()
    run_bruno_import(openapi, out, collection_name="Arrotech Hub API")
    coll = out / "arrotech-hub-api"
    assert (coll / "bruno.json").is_file()
    bru_files = list(coll.rglob("*.bru"))
    assert len(bru_files) >= 2
    login = next(p for p in bru_files if "login" in p.name.lower())
    text = login.read_text(encoding="utf-8")
    assert "{{baseUrl}}/auth/login" in text


def test_build_openapi_from_source_includes_spot_checks():
    from scripts.bruno_openapi import build_openapi_from_source

    spec = build_openapi_from_source()
    paths = spec["paths"]
    assert "/health" in paths
    assert "/auth/login" in paths
    assert "/auth/me" in paths
    assert any("whatsapp" in p.lower() for p in paths)
    assert any("workflow" in p.lower() for p in paths)
