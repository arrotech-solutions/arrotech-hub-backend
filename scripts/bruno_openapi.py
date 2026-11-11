"""Dump FastAPI OpenAPI JSON for Bruno workspace generation."""
from __future__ import annotations

import ast
import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[1]
HTTP_METHODS = {"get", "post", "put", "patch", "delete", "options", "head"}


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


def _literal_str(node: ast.AST) -> Optional[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _kw_str(call: ast.Call, name: str) -> Optional[str]:
    for kw in call.keywords:
        if kw.arg == name:
            return _literal_str(kw.value)
    return None


def _kw_list_str(call: ast.Call, name: str) -> list[str]:
    for kw in call.keywords:
        if kw.arg == name and isinstance(kw.value, (ast.List, ast.Tuple)):
            out = []
            for elt in kw.value.elts:
                s = _literal_str(elt)
                if s:
                    out.append(s)
            return out
    return []


def _join_paths(*parts: str) -> str:
    segs: list[str] = []
    for part in parts:
        if not part:
            continue
        segs.extend(p for p in part.split("/") if p)
    return "/" + "/".join(segs) if segs else "/"


def _router_file_prefix(tree: ast.AST) -> str:
    """Return prefix from ``router = APIRouter(prefix=...)`` if present."""
    for node in tree.body if isinstance(tree, ast.Module) else []:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == "router" for t in node.targets):
            continue
        if isinstance(node.value, ast.Call):
            func = node.value.func
            if isinstance(func, ast.Name) and func.id == "APIRouter":
                return _kw_str(node.value, "prefix") or ""
            if isinstance(func, ast.Attribute) and func.attr == "APIRouter":
                return _kw_str(node.value, "prefix") or ""
    return ""


def _extract_routes_from_file(path: Path) -> list[dict[str, Any]]:
    """Extract HTTP routes from a Python source file via AST."""
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except Exception as exc:
        logger.warning("Failed to parse %s: %s", path, exc)
        return []

    router_prefix = _router_file_prefix(tree)
    routes: list[dict[str, Any]] = []

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if not isinstance(dec, ast.Call):
                continue
            func = dec.func
            method = None
            if isinstance(func, ast.Attribute) and func.attr.lower() in HTTP_METHODS:
                method = func.attr.lower()
                # router.get / app.get / main_router.get
            else:
                continue
            if not dec.args:
                continue
            route_path = _literal_str(dec.args[0])
            if route_path is None:
                continue
            tags = _kw_list_str(dec, "tags")
            routes.append(
                {
                    "method": method,
                    "path": route_path,
                    "router_prefix": router_prefix,
                    "tags": tags,
                    "name": node.name,
                    "file": path.name,
                }
            )
    return routes


def _parse_main_mounts(main_path: Path) -> list[dict[str, Any]]:
    """
    Parse ``include_router`` calls in main.py.

    Returns dicts with keys: module (file stem hint), attr, prefix, tags.
    """
    source = main_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(main_path))
    mounts: list[dict[str, Any]] = []

    # Map import aliases: auth_router -> auth_router module file
    import_map: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module and "routers" in (node.module or ""):
            for alias in node.names:
                local = alias.asname or alias.name
                # e.g. from .routers import auth_router  OR from .routers.auth_router import router
                if node.module.endswith("routers"):
                    import_map[local] = alias.name  # module stem
                else:
                    # from .routers.whatsapp_webhook import router as ...
                    stem = node.module.rsplit(".", 1)[-1]
                    import_map[local] = stem

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute) or node.func.attr != "include_router":
            continue
        if not node.args:
            continue
        arg0 = node.args[0]
        module_stem = None
        attr = "router"
        if isinstance(arg0, ast.Name):
            module_stem = import_map.get(arg0.id, arg0.id)
            # access_router.router style sometimes imported as module
            if module_stem.endswith("_router") or module_stem in import_map.values():
                attr = "router"
        elif isinstance(arg0, ast.Attribute) and isinstance(arg0.value, ast.Name):
            module_stem = import_map.get(arg0.value.id, arg0.value.id)
            attr = arg0.attr
        else:
            continue

        mounts.append(
            {
                "module": module_stem,
                "attr": attr,
                "prefix": _kw_str(node, "prefix") or "",
                "tags": _kw_list_str(node, "tags"),
            }
        )
    return mounts


def _parse_nested_includes(router_file: Path) -> list[tuple[str, str, list[str]]]:
    """
    Find ``router.include_router(child...)`` in a router module.

    Returns list of (child_module_stem, extra_prefix_kw, tags_kw).
    Child's own APIRouter(prefix=...) is applied later via file scan.
    """
    try:
        tree = ast.parse(router_file.read_text(encoding="utf-8"), filename=str(router_file))
    except Exception:
        return []

    # local name -> module stem
    aliases: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                local = alias.asname or alias.name
                if alias.name.endswith("_router") or alias.name == "router":
                    if node.module and node.module.endswith(alias.name):
                        aliases[local] = alias.name
                    elif node.module == "." or (node.module or "").startswith("."):
                        aliases[local] = alias.name if alias.name != "router" else (
                            (node.module or "").rsplit(".", 1)[-1] or local
                        )
                    else:
                        aliases[local] = alias.name
                else:
                    aliases[local] = alias.name

    nested: list[tuple[str, str, list[str]]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute) or node.func.attr != "include_router":
            continue
        if not node.args:
            continue
        arg0 = node.args[0]
        child_stem = None
        if isinstance(arg0, ast.Attribute) and isinstance(arg0.value, ast.Name):
            child_stem = aliases.get(arg0.value.id, arg0.value.id)
        elif isinstance(arg0, ast.Name):
            child_stem = aliases.get(arg0.id, arg0.id)
        if not child_stem:
            continue
        if child_stem == "router":
            continue
        nested.append(
            (
                child_stem,
                _kw_str(node, "prefix") or "",
                _kw_list_str(node, "tags"),
            )
        )
    return nested


def build_openapi_from_source(repo_root: Optional[Path] = None) -> dict[str, Any]:
    """
    Build a synthetic OpenAPI 3 document by AST-scanning routers + main.py.

    Used when ``import src.main`` fails due to missing runtime dependencies.
    """
    root = Path(repo_root) if repo_root else REPO_ROOT
    routers_dir = root / "src" / "routers"
    main_path = root / "src" / "main.py"

    mounts = _parse_main_mounts(main_path) if main_path.exists() else []
    # module stem -> list of (mount_prefix, tags)
    mount_index: dict[str, list[tuple[str, list[str]]]] = {}
    for m in mounts:
        mount_index.setdefault(m["module"], []).append((m["prefix"], m["tags"]))

    # Expand one level of nested include_router (e.g. api_router → kra_router)
    for parent_stem, entries in list(mount_index.items()):
        parent_file = routers_dir / f"{parent_stem}.py"
        if not parent_file.exists():
            continue
        for child_stem, extra_prefix, extra_tags in _parse_nested_includes(parent_file):
            for parent_prefix, parent_tags in entries:
                mount_index.setdefault(child_stem, []).append(
                    (
                        _join_paths(parent_prefix, extra_prefix),
                        extra_tags or parent_tags,
                    )
                )

    paths: dict[str, dict[str, Any]] = {}

    def add_path(full: str, method: str, tags: list[str], summary: str) -> None:
        full = re.sub(r"/{2,}", "/", full)
        if not full.startswith("/"):
            full = "/" + full
        item = paths.setdefault(full, {})
        item[method] = {
            "summary": summary,
            "tags": tags or ["default"],
            "responses": {"200": {"description": "OK"}},
        }

    for py in sorted(routers_dir.glob("*.py")):
        if py.name == "__init__.py":
            continue
        stem = py.stem
        # Only emit routers that are actually mounted (directly or nested)
        if stem not in mount_index:
            continue
        file_routes = _extract_routes_from_file(py)
        for route in file_routes:
            for mount_prefix, mount_tags in mount_index[stem]:
                full = _join_paths(mount_prefix, route["router_prefix"], route["path"])
                tags = route["tags"] or mount_tags or [stem.replace("_router", "").replace("_", "-")]
                add_path(full, route["method"], tags, route["name"])

    # App-level routes last so they win collisions (e.g. GET /)
    if main_path.exists():
        for route in _extract_routes_from_file(main_path):
            add_path(route["path"], route["method"], route["tags"] or ["root"], route["name"])

    return {
        "openapi": "3.0.3",
        "info": {
            "title": "Arrotech Hub API",
            "version": "1.0.0",
            "description": "Generated from FastAPI router source (AST fallback).",
        },
        "servers": [{"url": "http://localhost:8000"}],
        "paths": paths,
    }


def dump_openapi(path: Path) -> dict[str, Any]:
    """Write OpenAPI schema to ``path`` and return the dict."""
    ensure_generation_env()
    spec: dict[str, Any]
    try:
        app = load_app()
        spec = app.openapi()
        logger.info("OpenAPI dumped from live FastAPI app (%s paths)", len(spec.get("paths", {})))
    except Exception as exc:
        logger.warning("Live app import failed (%s); using AST source fallback", exc)
        spec = build_openapi_from_source()
        logger.info("OpenAPI dumped via AST fallback (%s paths)", len(spec.get("paths", {})))

    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(spec, indent=2) + "\n", encoding="utf-8")
    return spec
