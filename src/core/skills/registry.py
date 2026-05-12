import threading
from typing import List, Dict, Optional
from .models import SkillDefinition, SkillCapability
from .exceptions import SkillValidationError, SkillNotFoundError

class SkillRegistry:
    _instance: Optional["SkillRegistry"] = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._skills = {}
        return cls._instance

    def register(self, skill: SkillDefinition):
        """Register a new skill."""
        if skill.name in self._skills:
            raise SkillValidationError(
                f"Skill already registered: {skill.name}"
            )

        self._skills[skill.name] = skill

    def get(self, name: str) -> SkillDefinition:
        """Get a skill by name."""
        if name not in self._skills:
            raise SkillNotFoundError(
                f"Skill not found: {name}"
            )

        return self._skills[name]

    def all(self) -> List[SkillDefinition]:
        """Get all registered skills."""
        return list(self._skills.values())

    def by_capability(
        self,
        capability: SkillCapability
    ) -> List[SkillDefinition]:
        """Get skills by capability."""
        return [
            s for s in self._skills.values()
            if s.capability == capability
        ]

    def _clear_for_testing(self):
        """Clear all registered skills (primarily for testing)."""
        self._skills.clear()
