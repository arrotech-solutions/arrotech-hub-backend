from typing import Set
from .models import SkillExecutionContract, SkillRiskLevel
from .exceptions import SkillValidationError
from .contracts import RegisteredToolRegistry

def validate_execution_contract(contract: SkillExecutionContract) -> None:
    """
    Validate a skill execution contract for governance, safety, and tool compatibility.
    """
    # 1. allowed_tools cannot be empty
    if not contract.allowed_tools:
        raise SkillValidationError("allowed_tools cannot be empty")

    # 2. tool existence, uniqueness, and capability compatibility
    tool_names: Set[str] = set()
    for tool_perm in contract.allowed_tools:
        # Check tool existence
        if not RegisteredToolRegistry.exists(tool_perm.tool_name):
            raise SkillValidationError(
                f"Unknown tool declared in contract: {tool_perm.tool_name}"
            )
        
        tool_def = RegisteredToolRegistry.get(tool_perm.tool_name)
        
        # RULE 1: Shell compatibility
        if tool_def.requires_shell and not contract.constraints.allow_shell_execution:
            raise SkillValidationError(
                f"Tool requires shell execution but contract forbids shell access: {tool_perm.tool_name}"
            )
            
        # RULE 2: Network compatibility
        if tool_def.requires_network and not contract.constraints.allow_network_access:
            raise SkillValidationError(
                f"Tool requires network access but contract forbids network access: {tool_perm.tool_name}"
            )
            
        # RULE 3: File mutation compatibility
        if tool_def.mutates_files and not contract.constraints.allow_file_mutation:
            raise SkillValidationError(
                f"Tool requires file mutation but contract forbids file mutation: {tool_perm.tool_name}"
            )
        
        # Tool uniqueness check
        if tool_perm.tool_name in tool_names:
            raise SkillValidationError(f"Duplicate tool permission: {tool_perm.tool_name}")
        tool_names.add(tool_perm.tool_name)

    # 3. HIGH and CRITICAL risk skills MUST require human approval
    if contract.risk_level in [SkillRiskLevel.HIGH, SkillRiskLevel.CRITICAL]:
        if not contract.constraints.require_human_approval:
            raise SkillValidationError(
                f"{contract.risk_level.upper()} risk skills MUST require human approval"
            )
