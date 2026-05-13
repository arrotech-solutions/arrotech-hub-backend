import time
from datetime import datetime, timezone
from src.core.skills.models import SkillDefinition
from src.core.skills.contracts import RegisteredToolRegistry
from src.core.skills.enforcer import SkillExecutionEnforcer
from .requests import ToolExecutionRequest
from .results import ToolExecutionResult
from .audit import audit_logger, ExecutionAuditRecord
from .sandbox import SandboxGovernance
from .registry import runtime_registry
from .exceptions import RuntimeAuthorizationError, RuntimeGovernanceError, RuntimeExecutionError

class GovernedToolExecutor:
    """
    Executes runtime tools strictly enforcing governance contracts BEFORE execution.
    """

    def execute(self, skill: SkillDefinition, request: ToolExecutionRequest) -> ToolExecutionResult:
        error_msg = None
        success = False
        start_time = time.perf_counter()
        execution_time_ms = 0
        output = {}

        try:
            # 0. Validate skill ownership
            if request.skill_name != skill.name:
                raise RuntimeAuthorizationError(f"Request skill name '{request.skill_name}' does not match context skill '{skill.name}'")

            tool_name = request.tool_name.strip().lower()

            # 1. Verify runtime tool exists
            if not runtime_registry.exists(tool_name):
                raise RuntimeAuthorizationError(f"Runtime tool not registered: {tool_name}")
            runtime_tool = runtime_registry.get(tool_name)

            # 2. Verify tool allowed by contract
            if not SkillExecutionEnforcer.is_tool_allowed(skill, tool_name):
                raise RuntimeAuthorizationError(f"Tool '{tool_name}' is not allowed by skill '{skill.name}' execution contract.")

            # 3. Verify environment allowed
            if request.environment not in skill.execution_contract.constraints.allowed_environments:
                raise RuntimeGovernanceError(f"Skill '{skill.name}' is not authorized to execute in environment '{request.environment.value}'.")

            # 4. Verify human approval if required
            if SkillExecutionEnforcer.requires_human_approval(skill) and not request.approved_by_human:
                raise RuntimeAuthorizationError(f"Skill '{skill.name}' requires human approval for execution.")

            # 5. Run sandbox governance validation
            # Get the static tool definition from the governance registry
            tool_def = RegisteredToolRegistry.get(tool_name)
            SandboxGovernance.validate(skill, tool_def)

            # 6. Execute tool (Deterministic execution, no async)
            tool_output = runtime_tool.execute(request)
            
            end_time = time.perf_counter()
            execution_time_ms = int((end_time - start_time) * 1000)
            
            success = tool_output.success
            output = tool_output.output
            if tool_output.error_message:
                error_msg = tool_output.error_message

            return ToolExecutionResult(
                success=success,
                tool_name=tool_name,
                execution_time_ms=execution_time_ms,
                output=output,
                error_message=error_msg
            )

        except (RuntimeAuthorizationError, RuntimeGovernanceError, RuntimeExecutionError) as e:
            end_time = time.perf_counter()
            execution_time_ms = int((end_time - start_time) * 1000)
            success = False
            error_msg = str(e)
            raise e
            
        finally:
            # 7. Generate audit record
            record = ExecutionAuditRecord(
                skill_name=request.skill_name,
                tool_name=request.tool_name.strip().lower(),
                timestamp=datetime.now(timezone.utc),
                execution_time_ms=execution_time_ms,
                success=success,
                approved_by_human=request.approved_by_human,
                environment=request.environment,
                error_message=error_msg
            )
            audit_logger.record(record)
