"""
Agent Memory Layer — Persistent architectural context for coding agents.

Stores and retrieves:
- Past execution summaries (what worked, what failed)
- Codebase conventions (patterns, naming, structure)
- Learned preferences (per-user and per-project)
- Error patterns and mitigations

This is the "long-term memory" that makes agents smarter over time.
"""
import logging
import time
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field
from collections import defaultdict

logger = logging.getLogger(__name__)


@dataclass
class MemoryEntry:
    """A single memory entry."""
    key: str
    category: str
    content: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    access_count: int = 0
    last_accessed: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "category": self.category,
            "content": self.content,
            "metadata": self.metadata,
            "access_count": self.access_count,
        }


class AgentMemoryStore:
    """
    In-memory store for agent context with category-based retrieval.

    Categories:
    - "convention": Code conventions and patterns
    - "execution": Past execution summaries
    - "error": Error patterns and mitigations
    - "preference": User/project preferences
    - "architecture": Architectural decisions and constraints

    Usage:
        memory = AgentMemoryStore()

        memory.remember("convention", "naming", "Use snake_case for Python files")
        memory.remember("error", "import_circular", "Avoid importing audit from immutability")

        context = memory.recall_context(categories=["convention", "error"])
        # Returns formatted string for system prompt injection
    """

    def __init__(self, max_entries_per_category: int = 100):
        self._store: Dict[str, Dict[str, MemoryEntry]] = defaultdict(dict)
        self._max_per_category = max_entries_per_category

    def remember(
        self,
        category: str,
        key: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> MemoryEntry:
        """
        Store a memory entry. Overwrites if key already exists.

        Args:
            category: Memory category (convention, execution, error, preference, architecture)
            key: Unique key within the category
            content: The memory content
            metadata: Optional structured metadata
        """
        entry = MemoryEntry(
            key=key,
            category=category,
            content=content,
            metadata=metadata or {},
        )

        cat_store = self._store[category]

        # Evict oldest if at capacity
        if key not in cat_store and len(cat_store) >= self._max_per_category:
            oldest_key = min(cat_store, key=lambda k: cat_store[k].created_at)
            del cat_store[oldest_key]

        cat_store[key] = entry
        logger.debug(f"Memory stored: [{category}] {key}")
        return entry

    def recall(self, category: str, key: str) -> Optional[MemoryEntry]:
        """Recall a specific memory entry."""
        entry = self._store.get(category, {}).get(key)
        if entry:
            entry.access_count += 1
            entry.last_accessed = time.time()
        return entry

    def recall_category(self, category: str) -> List[MemoryEntry]:
        """Recall all entries in a category."""
        entries = list(self._store.get(category, {}).values())
        for entry in entries:
            entry.access_count += 1
            entry.last_accessed = time.time()
        return entries

    def recall_context(
        self,
        categories: Optional[List[str]] = None,
        max_entries: int = 20,
    ) -> str:
        """
        Build a formatted context string for system prompt injection.

        Args:
            categories: Which categories to include (None = all)
            max_entries: Maximum total entries to include

        Returns:
            Formatted markdown string for prompt injection
        """
        if categories is None:
            categories = list(self._store.keys())

        sections = []
        total = 0

        for category in categories:
            entries = self.recall_category(category)
            if not entries:
                continue

            # Sort by access count (most accessed first)
            entries.sort(key=lambda e: e.access_count, reverse=True)

            items = []
            for entry in entries:
                if total >= max_entries:
                    break
                items.append(f"- {entry.content}")
                total += 1

            if items:
                header = category.replace("_", " ").title()
                sections.append(f"## {header}\n" + "\n".join(items))

        return "\n\n".join(sections) if sections else ""

    def search(self, query: str, categories: Optional[List[str]] = None) -> List[MemoryEntry]:
        """Simple keyword search across memory entries."""
        query_lower = query.lower()
        results = []

        target_categories = categories or list(self._store.keys())

        for category in target_categories:
            for entry in self._store.get(category, {}).values():
                if (
                    query_lower in entry.content.lower()
                    or query_lower in entry.key.lower()
                ):
                    results.append(entry)

        return results

    def forget(self, category: str, key: str) -> bool:
        """Remove a specific memory entry."""
        cat_store = self._store.get(category, {})
        if key in cat_store:
            del cat_store[key]
            return True
        return False

    def clear_category(self, category: str) -> int:
        """Clear all entries in a category. Returns count removed."""
        count = len(self._store.get(category, {}))
        self._store[category] = {}
        return count

    def stats(self) -> Dict[str, Any]:
        """Get memory statistics."""
        total = sum(len(entries) for entries in self._store.values())
        return {
            "total_entries": total,
            "categories": {
                cat: len(entries) for cat, entries in self._store.items()
            },
        }

    def export_all(self) -> Dict[str, List[Dict]]:
        """Export all memories for persistence."""
        return {
            category: [entry.to_dict() for entry in entries.values()]
            for category, entries in self._store.items()
        }


# Module-level singleton
agent_memory = AgentMemoryStore()

# Pre-populate with architectural knowledge
agent_memory.remember(
    "architecture", "governance_model",
    "All tool execution passes through GovernedCodingBridge which validates "
    "policy compliance and records to the tamper-evident audit chain."
)
agent_memory.remember(
    "architecture", "skill_system",
    "Skills are defined in YAML manifests with execution contracts specifying "
    "allowed tools, forbidden actions, risk levels, and environment constraints."
)
agent_memory.remember(
    "convention", "type_identity",
    "Use type(x) is T instead of isinstance(x, T) in governance-critical code "
    "to prevent subclass spoofing attacks."
)
agent_memory.remember(
    "convention", "immutability",
    "All runtime payloads must pass through freeze_structure() before audit "
    "recording. Use MappingProxyType for dicts and tuple for lists."
)
agent_memory.remember(
    "error", "circular_import",
    "Never import from audit.py in immutability.py — this creates a circular "
    "dependency. Serialization functions live in immutability.py."
)
agent_memory.remember(
    "error", "toctou_race",
    "Always use _pending_execution_ids reservation barrier in audit logging "
    "to prevent duplicate execution ID races under concurrency."
)
