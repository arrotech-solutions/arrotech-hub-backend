"""
Coding Agent — Tool Registry Definitions

All 24 tool definitions for the coding agent, following the exact same schema
as existing base tools in DynamicToolRegistry (name, description, inputSchema, category).

Tools are prefixed with 'coding_' to namespace them cleanly.
"""

CODING_AGENT_TOOLS = {
    # ═══════════════════════════════════════════════════════════════════
    # Category 1: Filesystem Tools (6)
    # ═══════════════════════════════════════════════════════════════════
    "coding_file_read": {
        "name": "coding_file_read",
        "description": "Read the contents of a file. Supports reading a specific line range to avoid loading large files entirely.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Active session ID"},
                "path": {"type": "string", "description": "Path to the file, relative to project root"},
                "start_line": {"type": "number", "description": "Optional. Read from this line (1-indexed)."},
                "end_line": {"type": "number", "description": "Optional. Read to this line (inclusive)."},
            },
            "required": ["session_id", "path"],
        },
        "category": "coding_agent",
        "always_available": True,
    },
    "coding_file_write": {
        "name": "coding_file_write",
        "description": "Create a new file or completely overwrite an existing file. Optionally creates parent directories. [SANDBOXED]",
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Active session ID"},
                "path": {"type": "string", "description": "Path to write to, relative to project root"},
                "content": {"type": "string", "description": "Full content to write"},
                "create_dirs": {"type": "boolean", "description": "Create missing parent dirs. Default: true", "default": True},
            },
            "required": ["session_id", "path", "content"],
        },
        "category": "coding_agent",
        "always_available": True,
    },
    "coding_file_edit": {
        "name": "coding_file_edit",
        "description": "Replace an exact string within a file. Preferred for targeted edits — do not rewrite entire files. old_str must be unique unless allow_multiple is true. [SANDBOXED]",
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Active session ID"},
                "path": {"type": "string", "description": "Path to the file to edit"},
                "old_str": {"type": "string", "description": "Exact string to find and replace. Must be unique."},
                "new_str": {"type": "string", "description": "Replacement string. Can be empty to delete."},
                "allow_multiple": {"type": "boolean", "description": "Replace all occurrences. Default: false", "default": False},
            },
            "required": ["session_id", "path", "old_str", "new_str"],
        },
        "category": "coding_agent",
        "always_available": True,
    },
    "coding_file_delete": {
        "name": "coding_file_delete",
        "description": "Delete a file from the workspace. [SANDBOXED]",
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Active session ID"},
                "path": {"type": "string", "description": "Path to the file to delete"},
                "require_exists": {"type": "boolean", "description": "Fail if file doesn't exist. Default: true", "default": True},
            },
            "required": ["session_id", "path"],
        },
        "category": "coding_agent",
        "always_available": True,
    },
    "coding_directory_list": {
        "name": "coding_directory_list",
        "description": "List directory contents with optional recursion. Returns formatted tree and structured array.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Active session ID"},
                "path": {"type": "string", "description": "Directory path relative to root. Use '.' for root.", "default": "."},
                "recursive": {"type": "boolean", "description": "List subdirs recursively. Default: false", "default": False},
                "max_depth": {"type": "number", "description": "Max depth when recursive. Default: 3", "default": 3},
                "include_hidden": {"type": "boolean", "description": "Include dot-files. Default: false", "default": False},
                "filter_extensions": {"type": "array", "items": {"type": "string"}, "description": "Only include these extensions. E.g. [\".ts\"]"},
            },
            "required": ["session_id"],
        },
        "category": "coding_agent",
        "always_available": True,
    },
    "coding_file_search": {
        "name": "coding_file_search",
        "description": "Find files by name pattern. Supports glob and plain name fragments.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Active session ID"},
                "pattern": {"type": "string", "description": "Filename pattern (glob or substring)"},
                "search_path": {"type": "string", "description": "Directory to search. Default: root", "default": "."},
                "case_sensitive": {"type": "boolean", "description": "Default: false", "default": False},
            },
            "required": ["session_id", "pattern"],
        },
        "category": "coding_agent",
        "always_available": True,
    },

    # ═══════════════════════════════════════════════════════════════════
    # Category 2: Code Search & Intelligence (2)
    # ═══════════════════════════════════════════════════════════════════
    "coding_grep_search": {
        "name": "coding_grep_search",
        "description": "Search for a string or regex pattern across file contents. Returns matches with surrounding context lines.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Active session ID"},
                "pattern": {"type": "string", "description": "String or regex pattern to search for"},
                "search_path": {"type": "string", "description": "File or directory. Default: root", "default": "."},
                "file_extensions": {"type": "array", "items": {"type": "string"}, "description": "Filter extensions. E.g. [\".ts\"]"},
                "case_sensitive": {"type": "boolean", "default": False},
                "context_lines": {"type": "number", "description": "Context lines before/after. Default: 3", "default": 3},
                "max_results": {"type": "number", "description": "Max matches. Default: 50", "default": 50},
            },
            "required": ["session_id", "pattern"],
        },
        "category": "coding_agent",
        "always_available": True,
    },
    "coding_get_definition": {
        "name": "coding_get_definition",
        "description": "Find where a symbol (function, class, variable, type) is defined in the codebase.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Active session ID"},
                "symbol_name": {"type": "string", "description": "Name of the function/class/variable to find"},
                "search_path": {"type": "string", "default": "."},
                "language": {"type": "string", "description": "Language hint: typescript, python, javascript"},
            },
            "required": ["session_id", "symbol_name"],
        },
        "category": "coding_agent",
        "always_available": True,
    },

    # ═══════════════════════════════════════════════════════════════════
    # Category 3: Command Execution (3) [ALL SANDBOXED]
    # ═══════════════════════════════════════════════════════════════════
    "coding_run_command": {
        "name": "coding_run_command",
        "description": "Execute a shell command in the project sandbox. Use for build, lint, format, type-check. NOT for tests — use coding_run_tests. [SANDBOXED]",
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Active session ID"},
                "command": {"type": "string", "description": "Shell command. E.g. 'npm run build'"},
                "working_directory": {"type": "string", "default": "."},
                "timeout_seconds": {"type": "number", "description": "Max seconds. Default: 60, Max: 300", "default": 60},
                "env": {"type": "object", "description": "Additional env vars", "additionalProperties": {"type": "string"}},
            },
            "required": ["session_id", "command"],
        },
        "category": "coding_agent",
        "always_available": True,
    },
    "coding_run_tests": {
        "name": "coding_run_tests",
        "description": "Run the test suite or a subset. Returns structured pass/fail counts. Auto-detects test framework. [SANDBOXED]",
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Active session ID"},
                "test_path": {"type": "string", "description": "Specific file or directory to test"},
                "test_filter": {"type": "string", "description": "Filter tests by name substring"},
                "working_directory": {"type": "string", "default": "."},
                "timeout_seconds": {"type": "number", "default": 120},
            },
            "required": ["session_id"],
        },
        "category": "coding_agent",
        "always_available": True,
    },
    "coding_install_dependencies": {
        "name": "coding_install_dependencies",
        "description": "Install packages or restore dependencies from lockfile inside sandbox. [SANDBOXED]",
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Active session ID"},
                "package_manager": {"type": "string", "enum": ["npm", "yarn", "pnpm", "pip", "cargo"]},
                "packages": {"type": "array", "items": {"type": "string"}, "description": "Specific packages. Empty = from lockfile."},
                "dev": {"type": "boolean", "description": "Install as dev dependency. Default: false", "default": False},
                "working_directory": {"type": "string", "default": "."},
            },
            "required": ["session_id", "package_manager"],
        },
        "category": "coding_agent",
        "always_available": True,
    },

    # ═══════════════════════════════════════════════════════════════════
    # Category 4: Git Tools (6)
    # ═══════════════════════════════════════════════════════════════════
    "coding_git_status": {
        "name": "coding_git_status",
        "description": "Get current git status — modified, staged, untracked files and branch info.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Active session ID"},
            },
            "required": ["session_id"],
        },
        "category": "coding_agent",
        "always_available": True,
    },
    "coding_git_diff": {
        "name": "coding_git_diff",
        "description": "Show changes in working directory, staged area, or between refs.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Active session ID"},
                "file_path": {"type": "string", "description": "Diff specific file only"},
                "staged": {"type": "boolean", "description": "Show staged changes. Default: false", "default": False},
                "base_ref": {"type": "string", "description": "Diff against this ref. E.g. 'main'"},
            },
            "required": ["session_id"],
        },
        "category": "coding_agent",
        "always_available": True,
    },
    "coding_git_commit": {
        "name": "coding_git_commit",
        "description": "Stage all changes and create a commit in the session workspace.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Active session ID"},
                "message": {"type": "string", "description": "Commit message. Use conventional commits: feat:, fix:, etc."},
                "author_name": {"type": "string", "default": "Arrotech Coding Agent"},
                "author_email": {"type": "string", "default": "agent@arrotechsolutions.com"},
                "add_all": {"type": "boolean", "description": "Stage all changes first. Default: true", "default": True},
            },
            "required": ["session_id", "message"],
        },
        "category": "coding_agent",
        "always_available": True,
    },
    "coding_git_push": {
        "name": "coding_git_push",
        "description": "Push the current branch to remote. Requires GitHub token.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Active session ID"},
                "remote": {"type": "string", "default": "origin"},
                "branch": {"type": "string", "description": "Branch to push. Default: current branch"},
                "force": {"type": "boolean", "default": False},
            },
            "required": ["session_id"],
        },
        "category": "coding_agent",
        "always_available": True,
    },
    "coding_git_create_branch": {
        "name": "coding_git_create_branch",
        "description": "Create a new branch from a given ref and check it out.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Active session ID"},
                "branch_name": {"type": "string", "description": "New branch name. Convention: agent/{description}"},
                "from_ref": {"type": "string", "description": "Branch from this ref. Default: main", "default": "main"},
            },
            "required": ["session_id", "branch_name"],
        },
        "category": "coding_agent",
        "always_available": True,
    },
    "coding_git_read_log": {
        "name": "coding_git_read_log",
        "description": "Read recent commit history, optionally filtered to a specific file.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Active session ID"},
                "max_commits": {"type": "number", "default": 20},
                "file_path": {"type": "string", "description": "Only show commits for this file"},
            },
            "required": ["session_id"],
        },
        "category": "coding_agent",
        "always_available": True,
    },

    # ═══════════════════════════════════════════════════════════════════
    # Category 5: Context & Memory (4)
    # ═══════════════════════════════════════════════════════════════════
    "coding_read_file_summary": {
        "name": "coding_read_file_summary",
        "description": "Get structural summary of a file — imports, exports, declarations — without reading full content.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Active session ID"},
                "path": {"type": "string", "description": "Path to the file to summarize"},
            },
            "required": ["session_id", "path"],
        },
        "category": "coding_agent",
        "always_available": True,
    },
    "coding_get_project_structure": {
        "name": "coding_get_project_structure",
        "description": "Returns high-level project overview — framework, language, test framework, config files, directory tree. Call at session start.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Active session ID"},
            },
            "required": ["session_id"],
        },
        "category": "coding_agent",
        "always_available": True,
    },
    "coding_write_scratchpad": {
        "name": "coding_write_scratchpad",
        "description": "Write notes to the agent's scratchpad. Use to store your plan and track progress.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Active session ID"},
                "content": {"type": "string", "description": "Content to write"},
                "append": {"type": "boolean", "description": "Append to existing. Default: false", "default": False},
            },
            "required": ["session_id", "content"],
        },
        "category": "coding_agent",
        "always_available": True,
    },
    "coding_read_scratchpad": {
        "name": "coding_read_scratchpad",
        "description": "Read the current scratchpad contents for this session.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Active session ID"},
            },
            "required": ["session_id"],
        },
        "category": "coding_agent",
        "always_available": True,
    },

    # ═══════════════════════════════════════════════════════════════════
    # Category 6: GitHub / PR Tools (3)
    # ═══════════════════════════════════════════════════════════════════
    "coding_github_create_pr": {
        "name": "coding_github_create_pr",
        "description": "Open a pull request on GitHub after pushing the agent's branch.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Active session ID"},
                "repo": {"type": "string", "description": "Repository in 'owner/repo' format"},
                "title": {"type": "string", "description": "PR title"},
                "body": {"type": "string", "description": "PR description with change summary"},
                "head_branch": {"type": "string", "description": "Branch with agent's changes"},
                "base_branch": {"type": "string", "default": "main"},
                "draft": {"type": "boolean", "default": False},
            },
            "required": ["session_id", "repo", "title", "body", "head_branch"],
        },
        "category": "coding_agent",
        "always_available": True,
    },
    "coding_github_get_pr_status": {
        "name": "coding_github_get_pr_status",
        "description": "Poll CI check status on a pull request.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Active session ID"},
                "repo": {"type": "string", "description": "Repository in 'owner/repo' format"},
                "pr_number": {"type": "number", "description": "PR number to check"},
            },
            "required": ["session_id", "repo", "pr_number"],
        },
        "category": "coding_agent",
        "always_available": True,
    },
    "coding_github_get_check_logs": {
        "name": "coding_github_get_check_logs",
        "description": "Download full logs from a specific CI check run.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Active session ID"},
                "repo": {"type": "string", "description": "Repository in 'owner/repo' format"},
                "check_run_id": {"type": "number", "description": "Check run ID from coding_github_get_pr_status"},
            },
            "required": ["session_id", "repo", "check_run_id"],
        },
        "category": "coding_agent",
        "always_available": True,
    },

    # ═══════════════════════════════════════════════════════════════════
    # Category 5: Planning Tools (3)
    # ═══════════════════════════════════════════════════════════════════
    "coding_create_plan": {
        "name": "coding_create_plan",
        "description": "Create a new execution plan with structured tasks. Use this for complex, multi-step goals before executing.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Active session ID"},
                "goal": {"type": "string", "description": "High-level goal of the plan"},
                "tasks": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string", "description": "Short title of the task"},
                            "description": {"type": "string", "description": "Detailed description"},
                            "skill_name": {"type": "string", "description": "Skill needed (e.g., coding_write, coding_read)"},
                            "tools_needed": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Tools that will likely be used"
                            },
                            "depends_on": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "IDs of tasks that must complete first (if any). Omit if no dependencies."
                            }
                        },
                        "required": ["title"]
                    }
                }
            },
            "required": ["goal", "tasks"]
        },
        "category": "planning",
        "always_available": True,
    },
    "coding_update_task": {
        "name": "coding_update_task",
        "description": "Update the status of a planned task. Call this as you make progress on a plan.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Active session ID"},
                "task_id": {"type": "string", "description": "ID of the task to update"},
                "status": {"type": "string", "enum": ["in_progress", "completed", "failed", "skipped"]},
                "output": {"type": "string", "description": "Output or error message to record"}
            },
            "required": ["task_id", "status"]
        },
        "category": "planning",
        "always_available": True,
    },
    "coding_get_plan": {
        "name": "coding_get_plan",
        "description": "Get the current active execution plan and its status.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Active session ID"}
            }
        },
        "category": "planning",
        "always_available": True,
    }
}
