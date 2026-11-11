"""Convert OpenAPI JSON into a classic Bruno (.bru) collection."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

HTTP_METHODS = ("get", "post", "put", "patch", "delete", "options", "head")


def _safe_name(value: str) -> str:
    cleaned = re.sub(r"[^\w\- ]+", " ", value).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned[:80] or "request"


def _folder_name(tags: list[str], fallback: str) -> str:
    tag = tags[0] if tags else fallback
    return _safe_name(tag).replace(" ", "-").lower() or "default"


def _request_name(method: str, path: str, operation: dict[str, Any]) -> str:
    if operation.get("summary"):
        return _safe_name(str(operation["summary"]))
    if operation.get("operationId"):
        return _safe_name(str(operation["operationId"]))
    return _safe_name(f"{method.upper()} {path}")


def _bru_file_name(name: str, method: str) -> str:
    base = re.sub(r"[^\w\-]+", "-", name.lower()).strip("-")
    return f"{method}-{base}"[:100] + ".bru"


def _example_body(operation: dict[str, Any]) -> str | None:
    body = operation.get("requestBody") or {}
    content = body.get("content") or {}
    app_json = content.get("application/json") or {}
    if "example" in app_json:
        return json.dumps(app_json["example"], indent=2)
    schema = app_json.get("schema") or {}
    if schema.get("example"):
        return json.dumps(schema["example"], indent=2)
    # login helper
    return None


def _write_bru(
    path: Path,
    *,
    name: str,
    method: str,
    url: str,
    seq: int,
    body_json: str | None,
) -> None:
    lines = [
        "meta {",
        f"  name: {name}",
        "  type: http",
        f"  seq: {seq}",
        "}",
        "",
        f"{method} {{",
        f"  url: {url}",
        f"  body: {'json' if body_json else 'none'}",
        "  auth: inherit",
        "}",
        "",
    ]
    if body_json:
        lines.extend(["body:json {", body_json, "}", ""])
    path.write_text("\n".join(lines), encoding="utf-8")


def write_bru_collection_from_openapi(
    openapi_path: Path,
    collection_dir: Path,
    collection_name: str = "Arrotech Hub API",
) -> int:
    """
    Write a Bruno collection (bruno.json + .bru requests) from OpenAPI.

    Returns the number of request files written.
    """
    spec = json.loads(Path(openapi_path).read_text(encoding="utf-8"))
    paths = spec.get("paths") or {}
    collection_dir = Path(collection_dir)
    if collection_dir.exists():
        # caller may already have cleared; ensure clean request tree except we recreate
        pass
    collection_dir.mkdir(parents=True, exist_ok=True)

    (collection_dir / "bruno.json").write_text(
        json.dumps(
            {
                "version": "1",
                "name": collection_name,
                "type": "collection",
                "ignore": ["node_modules", ".git"],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (collection_dir / "collection.bru").write_text(
        "meta {\n  name: " + collection_name + "\n}\n\n"
        "auth {\n  mode: inherit\n}\n\n"
        "script:pre-request {\n  // Cookie jar: run Auth/login first\n}\n",
        encoding="utf-8",
    )

    count = 0
    seq_by_folder: dict[str, int] = {}
    for api_path, operations in sorted(paths.items()):
        if not isinstance(operations, dict):
            continue
        for method in HTTP_METHODS:
            if method not in operations:
                continue
            op = operations[method] or {}
            tags = op.get("tags") or ["default"]
            folder = _folder_name(tags, "default")
            folder_dir = collection_dir / folder
            folder_dir.mkdir(parents=True, exist_ok=True)
            if not (folder_dir / "folder.bru").exists():
                (folder_dir / "folder.bru").write_text(
                    f"meta {{\n  name: {folder}\n}}\n",
                    encoding="utf-8",
                )
            seq_by_folder[folder] = seq_by_folder.get(folder, 0) + 1
            seq = seq_by_folder[folder]
            name = _request_name(method, api_path, op)
            url = "{{baseUrl}}" + (api_path if api_path.startswith("/") else "/" + api_path)
            body = None
            if method in {"post", "put", "patch"}:
                body = _example_body(op)
                if body is None and api_path.rstrip("/").endswith("/auth/login"):
                    body = '{\n  "email": "{{email}}",\n  "password": "{{password}}"\n}'
                elif body is None:
                    body = "{}"
            file_path = folder_dir / _bru_file_name(name, method)
            # avoid collisions
            if file_path.exists():
                file_path = folder_dir / _bru_file_name(f"{name}-{seq}", method)
            _write_bru(
                file_path,
                name=name,
                method=method,
                url=url,
                seq=seq,
                body_json=body,
            )
            count += 1
    return count
