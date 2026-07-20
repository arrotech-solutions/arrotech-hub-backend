import yaml
from pathlib import Path
from pydantic import ValidationError
from .models import SkillDefinition
from .exceptions import SkillLoadError
from .validators import validate_execution_contract
import logging

logger = logging.getLogger(__name__)

def load_skill(path: Path) -> SkillDefinition:
    """
    Load a skill definition from a YAML file.
    
    Args:
        path: Path to the skill.yaml file
        
    Returns:
        SkillDefinition: The validated skill definition
        
    Raises:
        SkillLoadError: If the file is missing, malformed, or fails validation
    """
    if not path.exists():
        raise SkillLoadError(
            f"Skill file not found: {path}"
        )

    if not path.is_file():
        raise SkillLoadError(
            f"Skill path is not a file: {path}"
        )

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

    except FileNotFoundError as e:
        raise SkillLoadError(
            f"Skill file not found: {path}"
        ) from e

    except yaml.YAMLError as e:
        raise SkillLoadError(
            f"Malformed YAML in {path}: {e}"
        ) from e

    if data is None:
        raise SkillLoadError(
            f"Skill file is empty: {path}"
        )

    try:
        skill = SkillDefinition(**data)
        # Validate execution contract
        validate_execution_contract(skill.execution_contract)
        logger.info(f"Validated execution contract: {skill.name}")
        return skill

    except ValidationError as e:
        raise SkillLoadError(
            f"Skill validation failed for {path}: {e}"
        ) from e
