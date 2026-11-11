"""Generate the committed Bruno workspace from FastAPI OpenAPI."""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.bruno_openapi import dump_openapi
from scripts.bruno_workspace_patch import (
    patch_collection_base_url,
    write_readme_if_missing,
    write_workspace_scaffold,
)

COLLECTION_DIRNAME = "arrotech-hub-api"
DEFAULT_COLLECTION_NAME = "Arrotech Hub API"
DEFAULT_BRUNO_ROOT = REPO_ROOT / "bruno"


def _bruno_cli_prefix() -> list[str]:
    bru = shutil.which("bru")
    if bru:
        return [bru]
    npx = shutil.which("npx")
    if not npx:
        raise RuntimeError(
            "Neither 'bru' nor 'npx' found on PATH. Install Bruno CLI or Node.js."
        )
    return [npx, "--yes", "@usebruno/cli"]


def run_bruno_import(
    openapi_path: Path,
    output_dir: Path,
    collection_name: str = DEFAULT_COLLECTION_NAME,
) -> None:
    """Import OpenAPI into a Bruno OpenCollection under ``output_dir``."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    prefix = _bruno_cli_prefix()
    argv = [
        *prefix,
        "import",
        "openapi",
        "--source",
        str(openapi_path),
        "--output",
        str(output_dir),
        "--collection-name",
        collection_name,
        "--collection-format",
        "opencollection",
    ]
    result = subprocess.run(argv, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"Bruno import failed with exit code {result.returncode}: {argv}")


def _normalize_collection_dir(collections_dir: Path) -> Path:
    """Ensure the imported collection lives at collections/arrotech-hub-api."""
    target = collections_dir / COLLECTION_DIRNAME
    if target.exists() and (target / "opencollection.yml").exists():
        return target
    if target.exists() and (target / "bruno.json").exists():
        return target

    candidates = [
        p
        for p in collections_dir.iterdir()
        if p.is_dir()
        and (
            (p / "opencollection.yml").exists()
            or (p / "bruno.json").exists()
        )
    ]
    if not candidates:
        raise RuntimeError(
            f"Bruno import produced no collection under {collections_dir}"
        )
    # Prefer exact slug match; else newest/only collection
    preferred = None
    for p in candidates:
        if p.name.lower().replace(" ", "-") in {
            COLLECTION_DIRNAME,
            "arrotech-hub-api",
            "arrotech hub api".replace(" ", "-"),
        }:
            preferred = p
            break
    src = preferred or candidates[0]
    if src.resolve() != target.resolve():
        if target.exists():
            shutil.rmtree(target)
        src.rename(target)
    return target


def generate(bruno_root: Path) -> None:
    """Dump OpenAPI, import into Bruno, scaffold workspace, patch URLs."""
    root = Path(bruno_root)
    root.mkdir(parents=True, exist_ok=True)
    write_workspace_scaffold(root)
    write_readme_if_missing(root)

    openapi_path = root / "openapi.json"
    dump_openapi(openapi_path)

    collections_dir = root / "collections"
    collections_dir.mkdir(parents=True, exist_ok=True)
    existing = collections_dir / COLLECTION_DIRNAME
    if existing.exists():
        shutil.rmtree(existing)

    run_bruno_import(openapi_path, collections_dir, collection_name=DEFAULT_COLLECTION_NAME)
    collection_dir = _normalize_collection_dir(collections_dir)
    patch_collection_base_url(collection_dir)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate Bruno workspace from OpenAPI")
    parser.add_argument(
        "--bruno-root",
        type=Path,
        default=DEFAULT_BRUNO_ROOT,
        help="Workspace output directory (default: <repo>/bruno)",
    )
    args = parser.parse_args(argv)
    generate(args.bruno_root)
    print(f"Bruno workspace ready at {args.bruno_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
