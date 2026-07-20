import re
from typing import List
from .models import SkillDefinition
from .registry import SkillRegistry

def match_skills(
    task: str,
    registry: SkillRegistry
) -> List[SkillDefinition]:
    """
    Match skills based on lexical triggers in the task description using word-boundary regex.
    
    Args:
        task: The task description string
        registry: The skill registry to match against
        
    Returns:
        List[SkillDefinition]: Sorted list of matching skills (descending by score)
    """
    task_lower = task.lower()
    matches = []
    
    for skill in registry.all():
        score = 0
        for trigger in skill.triggers:
            # Use regex word-boundary matching to prevent false positives (e.g., "contest" matching "test")
            pattern = r"\b" + re.escape(trigger.lower()) + r"\b"
            occurrences = len(re.findall(pattern, task_lower))
            score += occurrences
        
        if score > 0:
            matches.append((skill, score))
            
    # Sort descending by score
    matches.sort(key=lambda x: x[1], reverse=True)
    
    return [m[0] for m in matches]
