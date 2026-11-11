"""Generate the committed Bruno workspace from FastAPI OpenAPI."""
from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path


def _rmtree_retry(path: Path, attempts: int = 5) -> None:
    """Remove a directory, retrying on Windows/OneDrive locks."""
    if not path.exists():
        return
    last_err: Exception | None = None
    for i in range(attempts):
        try:
            shutil.rmtree(path)
            return
        except PermissionError as exc:
            last_err = exc
            time.sleep(0.4 * (i + 1))
    raise RuntimeError(f"Could not remove {path}: {last_err}")

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.bruno_from_openapi import write_bru_collection_from_openapi
from scripts.bruno_openapi import dump_openapi
from scripts.bruno_workspace_patch import (
    patch_collection_base_url,
    write_readme_if_missing,
    write_workspace_scaffold,
)

COLLECTION_DIRNAME = "arrotech-hub-api"
DEFAULT_COLLECTION_NAME = "Arrotech Hub API"
DEFAULT_BRUNO_ROOT = REPO_ROOT / "bruno"


def run_bruno_import(
    openapi_path: Path,
    output_dir: Path,
    collection_name: str = DEFAULT_COLLECTION_NAME,
) -> None:
    """
    Build a Bruno collection from OpenAPI into ``output_dir/<slug>``.

    Uses an in-repo OpenAPI→``.bru`` writer (Bruno CLI is optional/unreliable
    across environments). Writes via a staging directory so Windows/OneDrive
    locks on the live collection folder do not block regeneration.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    collection_dir = output_dir / COLLECTION_DIRNAME
    staging = output_dir / f"{COLLECTION_DIRNAME}.staging"
    _rmtree_retry(staging)
    staging.mkdir(parents=True, exist_ok=True)
    n = write_bru_collection_from_openapi(
        openapi_path, staging, collection_name=collection_name
    )
    if n <= 0:
        raise RuntimeError(f"No requests generated from {openapi_path}")

    # Promote staging → live collection
    trash = output_dir / f"{COLLECTION_DIRNAME}.trash"
    _rmtree_retry(trash)
    if collection_dir.exists():
        try:
            collection_dir.rename(trash)
        except OSError:
            # Fall back to in-place clear when rename is locked
            _rmtree_retry(collection_dir)
    staging.rename(collection_dir)
    try:
        _rmtree_retry(trash)
    except RuntimeError:
        # OneDrive/Windows may keep locks; leave .trash for later cleanup
        pass


def generate(bruno_root: Path) -> None:
    """Dump OpenAPI, build Bruno collection, scaffold workspace, patch URLs."""
    root = Path(bruno_root)
    root.mkdir(parents=True, exist_ok=True)
    write_workspace_scaffold(root)
    write_readme_if_missing(root)

    openapi_path = root / "openapi.json"
    dump_openapi(openapi_path)

    collections_dir = root / "collections"
    collections_dir.mkdir(parents=True, exist_ok=True)
    run_bruno_import(openapi_path, collections_dir, collection_name=DEFAULT_COLLECTION_NAME)
    collection_dir = collections_dir / COLLECTION_DIRNAME
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
