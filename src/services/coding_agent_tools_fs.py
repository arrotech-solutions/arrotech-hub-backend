"""
Coding Agent — Tool Executor (Part 1: Filesystem, Search, Context)
Handles: file_read, file_write, file_edit, file_delete, directory_list,
file_search, grep_search, get_definition, read_file_summary,
get_project_structure, write_scratchpad, read_scratchpad
"""
import fnmatch
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional

from .coding_agent_helpers import (
    IGNORED_DIRS, build_tool_envelope, is_binary_file,
    safe_path, should_ignore_dir, truncate_output,
)

logger = logging.getLogger(__name__)


async def handle_file_read(args: Dict, workspace: str) -> Dict:
    path = safe_path(workspace, args["path"])
    if not os.path.isfile(path):
        raise FileNotFoundError(f"File not found: {args['path']}")
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    start = max(1, int(args.get("start_line", 1))) - 1
    end = int(args.get("end_line", len(lines)))
    selected = lines[start:end]
    return {
        "content": "".join(selected),
        "total_lines": len(lines),
        "lines_shown": f"{start+1}-{min(end, len(lines))}",
        "path": args["path"],
    }


async def handle_file_write(args: Dict, workspace: str) -> Dict:
    path = safe_path(workspace, args["path"])
    if args.get("create_dirs", True):
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
    existed = os.path.exists(path)
    with open(path, "w", encoding="utf-8") as f:
        f.write(args["content"])
    return {"path": args["path"], "bytes_written": len(args["content"]), "created": not existed}


async def handle_file_edit(args: Dict, workspace: str) -> Dict:
    path = safe_path(workspace, args["path"])
    if not os.path.isfile(path):
        raise FileNotFoundError(f"File not found: {args['path']}")
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    old_str = args["old_str"]
    count = content.count(old_str)
    if count == 0:
        raise ValueError(f"old_str not found in {args['path']}")
    if count > 1 and not args.get("allow_multiple", False):
        raise ValueError(f"old_str found {count} times. Set allow_multiple=true or make old_str more specific.")
    new_content = content.replace(old_str, args["new_str"]) if args.get("allow_multiple") else content.replace(old_str, args["new_str"], 1)
    with open(path, "w", encoding="utf-8") as f:
        f.write(new_content)
    return {"path": args["path"], "replacements": count if args.get("allow_multiple") else 1}


async def handle_file_delete(args: Dict, workspace: str) -> Dict:
    path = safe_path(workspace, args["path"])
    if not os.path.exists(path):
        if args.get("require_exists", True):
            raise FileNotFoundError(f"File not found: {args['path']}")
        return {"path": args["path"], "deleted": False}
    os.remove(path)
    return {"path": args["path"], "deleted": True}


async def handle_directory_list(args: Dict, workspace: str) -> Dict:
    path = safe_path(workspace, args.get("path", "."))
    if not os.path.isdir(path):
        raise NotADirectoryError(f"Not a directory: {args.get('path', '.')}")
    recursive = args.get("recursive", False)
    max_depth = args.get("max_depth", 3)
    include_hidden = args.get("include_hidden", False)
    filter_ext = set(args.get("filter_extensions", []))
    entries = []
    tree_lines = []

    def walk(dir_path, depth, prefix=""):
        if depth > max_depth and recursive:
            return
        try:
            items = sorted(os.listdir(dir_path))
        except PermissionError:
            return
        for item in items:
            if not include_hidden and item.startswith("."):
                continue
            if should_ignore_dir(item):
                continue
            full = os.path.join(dir_path, item)
            rel = os.path.relpath(full, workspace)
            is_dir = os.path.isdir(full)
            if filter_ext and not is_dir:
                _, ext = os.path.splitext(item)
                if ext not in filter_ext:
                    continue
            size = os.path.getsize(full) if not is_dir else None
            entries.append({"name": item, "path": rel, "type": "directory" if is_dir else "file", "size": size})
            icon = "📁" if is_dir else "📄"
            tree_lines.append(f"{prefix}{icon} {item}")
            if is_dir and recursive:
                walk(full, depth + 1, prefix + "  ")

    walk(path, 0)
    return {"entries": entries[:500], "tree": "\n".join(tree_lines[:500]), "total": len(entries)}


async def handle_file_search(args: Dict, workspace: str) -> Dict:
    search_path = safe_path(workspace, args.get("search_path", "."))
    pattern = args["pattern"]
    case_sensitive = args.get("case_sensitive", False)
    if not case_sensitive:
        pattern_lower = pattern.lower()
    matches = []
    for root, dirs, files in os.walk(search_path):
        dirs[:] = [d for d in dirs if not should_ignore_dir(d)]
        for f in files:
            name = f if case_sensitive else f.lower()
            pat = pattern if case_sensitive else pattern_lower
            if fnmatch.fnmatch(name, pat) or pat in name:
                rel = os.path.relpath(os.path.join(root, f), workspace)
                matches.append(rel)
                if len(matches) >= 100:
                    return {"matches": matches, "truncated": True}
    return {"matches": matches, "truncated": False}


async def handle_grep_search(args: Dict, workspace: str) -> Dict:
    search_path = safe_path(workspace, args.get("search_path", "."))
    pattern = args["pattern"]
    case_sensitive = args.get("case_sensitive", False)
    context_lines = args.get("context_lines", 3)
    max_results = args.get("max_results", 50)
    file_ext = set(args.get("file_extensions", []))
    flags = 0 if case_sensitive else re.IGNORECASE
    try:
        regex = re.compile(pattern, flags)
    except re.error:
        regex = re.compile(re.escape(pattern), flags)
    results = []
    files_to_search = []
    if os.path.isfile(search_path):
        files_to_search = [search_path]
    else:
        for root, dirs, files in os.walk(search_path):
            dirs[:] = [d for d in dirs if not should_ignore_dir(d)]
            for f in files:
                if is_binary_file(f):
                    continue
                if file_ext:
                    _, ext = os.path.splitext(f)
                    if ext not in file_ext:
                        continue
                files_to_search.append(os.path.join(root, f))

    for fpath in files_to_search:
        if len(results) >= max_results:
            break
        try:
            with open(fpath, "r", encoding="utf-8", errors="replace") as fh:
                lines = fh.readlines()
        except Exception:
            continue
        for i, line in enumerate(lines):
            if regex.search(line):
                start = max(0, i - context_lines)
                end = min(len(lines), i + context_lines + 1)
                ctx = "".join(lines[start:end])
                rel = os.path.relpath(fpath, workspace)
                results.append({"file": rel, "line": i + 1, "match": line.rstrip(), "context": ctx})
                if len(results) >= max_results:
                    break
    return {"results": results, "total_matches": len(results)}


async def handle_get_definition(args: Dict, workspace: str) -> Dict:
    symbol = args["symbol_name"]
    search_path = safe_path(workspace, args.get("search_path", "."))
    lang = args.get("language", "").lower()
    patterns = {
        "python": [rf"^(class|def|async def)\s+{re.escape(symbol)}\b", rf"^{re.escape(symbol)}\s*="],
        "typescript": [rf"(export\s+)?(function|class|const|let|var|type|interface|enum)\s+{re.escape(symbol)}\b"],
        "javascript": [rf"(export\s+)?(function|class|const|let|var)\s+{re.escape(symbol)}\b"],
    }
    lang_patterns = patterns.get(lang, list(set(p for ps in patterns.values() for p in ps)))
    regexes = [re.compile(p, re.MULTILINE) for p in lang_patterns]
    ext_map = {"python": {".py"}, "typescript": {".ts", ".tsx"}, "javascript": {".js", ".jsx"}}
    exts = ext_map.get(lang, set())
    defs = []
    for root, dirs, files in os.walk(search_path):
        dirs[:] = [d for d in dirs if not should_ignore_dir(d)]
        for f in files:
            if is_binary_file(f):
                continue
            if exts:
                _, ext = os.path.splitext(f)
                if ext not in exts:
                    continue
            fpath = os.path.join(root, f)
            try:
                with open(fpath, "r", encoding="utf-8", errors="replace") as fh:
                    content = fh.read()
            except Exception:
                continue
            for rx in regexes:
                for m in rx.finditer(content):
                    line_num = content[:m.start()].count("\n") + 1
                    lines = content.splitlines()
                    ctx_start = max(0, line_num - 3)
                    ctx_end = min(len(lines), line_num + 5)
                    defs.append({
                        "file": os.path.relpath(fpath, workspace),
                        "line": line_num, "match": m.group().strip(),
                        "context": "\n".join(lines[ctx_start:ctx_end]),
                    })
            if len(defs) >= 20:
                break
        if len(defs) >= 20:
            break
    return {"symbol": symbol, "definitions": defs}


async def handle_read_file_summary(args: Dict, workspace: str) -> Dict:
    path = safe_path(workspace, args["path"])
    if not os.path.isfile(path):
        raise FileNotFoundError(f"File not found: {args['path']}")
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()
    lines = content.splitlines()
    _, ext = os.path.splitext(path)
    imports, exports, declarations = [], [], []
    for i, line in enumerate(lines):
        stripped = line.strip()
        if re.match(r"^(import |from .+ import |require\(|const .+ = require)", stripped):
            imports.append({"line": i + 1, "text": stripped})
        elif re.match(r"^(export |module\.exports)", stripped):
            exports.append({"line": i + 1, "text": stripped})
        elif re.match(r"^(def |async def |class |function |const |let |var |type |interface |enum )", stripped):
            declarations.append({"line": i + 1, "text": stripped[:120]})
    return {
        "path": args["path"], "total_lines": len(lines), "extension": ext,
        "imports": imports[:30], "exports": exports[:30], "declarations": declarations[:50],
    }


async def handle_get_project_structure(args: Dict, workspace: str) -> Dict:
    # Detect framework, language, package manager, test framework
    detected = {"framework": None, "language": None, "package_manager": None, "test_framework": None}
    config_files = []
    for f in os.listdir(workspace):
        if os.path.isfile(os.path.join(workspace, f)):
            config_files.append(f)
    if "package.json" in config_files:
        detected["language"] = "javascript/typescript"
        if "yarn.lock" in config_files: detected["package_manager"] = "yarn"
        elif "pnpm-lock.yaml" in config_files: detected["package_manager"] = "pnpm"
        else: detected["package_manager"] = "npm"
        try:
            import json
            with open(os.path.join(workspace, "package.json")) as f:
                pkg = json.load(f)
            deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
            if "next" in deps: detected["framework"] = "Next.js"
            elif "react" in deps: detected["framework"] = "React"
            elif "vue" in deps: detected["framework"] = "Vue"
            elif "express" in deps: detected["framework"] = "Express"
            if "jest" in deps: detected["test_framework"] = "jest"
            elif "vitest" in deps: detected["test_framework"] = "vitest"
            elif "mocha" in deps: detected["test_framework"] = "mocha"
        except Exception:
            pass
    elif "requirements.txt" in config_files or "pyproject.toml" in config_files:
        detected["language"] = "python"
        detected["package_manager"] = "pip"
        if "pytest.ini" in config_files or "conftest.py" in config_files:
            detected["test_framework"] = "pytest"
    elif "Cargo.toml" in config_files:
        detected["language"] = "rust"
        detected["package_manager"] = "cargo"
    # Build tree (depth 2)
    tree_result = await handle_directory_list(
        {"path": ".", "recursive": True, "max_depth": 2}, workspace
    )
    return {
        "detected": detected, "config_files": config_files[:30],
        "tree": tree_result.get("tree", ""), "total_entries": tree_result.get("total", 0),
    }


async def handle_write_scratchpad(args: Dict, session) -> Dict:
    mode = "a" if args.get("append", False) else "w"
    with open(session.scratchpad_path, mode, encoding="utf-8") as f:
        f.write(args["content"])
        if not args["content"].endswith("\n"):
            f.write("\n")
    size = os.path.getsize(session.scratchpad_path)
    return {"bytes_written": len(args["content"]), "total_size": size, "mode": "append" if mode == "a" else "overwrite"}


async def handle_read_scratchpad(args: Dict, session) -> Dict:
    if not os.path.exists(session.scratchpad_path):
        return {"content": "", "empty": True}
    with open(session.scratchpad_path, "r", encoding="utf-8") as f:
        content = f.read()
    return {"content": content, "empty": not content.strip()}
