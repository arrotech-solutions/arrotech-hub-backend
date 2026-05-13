import time
from src.core.skills.models import SkillDefinition
from src.core.skills.contracts import RegisteredToolRegistry
from src.core.skills.enforcer import SkillExecutionEnforcer
from .requests import ToolExecutionRequest
from .results import ToolExecutionResult
from .audit import audit_logger
from .sandbox import SandboxGovernance
from .registry import runtime_registry
from .exceptions import RuntimeAuthorizationError, RuntimeGovernanceError, RuntimeExecutionError, RuntimeTimeoutError
from .validators import validate_tool_output
from .factory import ExecutionResultFactory

class GovernedToolExecutor:
    """
    Executes runtime tools strictly enforcing governance contracts BEFORE execution.
    """
    def _elapsed_ms(self, start_time: float) -> int:
        """Calculate elapsed milliseconds using monotonic clock."""
        return int((time.perf_counter() - start_time) * 1000)

    def _finalize_failure(
        self,
        *,
        request: ToolExecutionRequest,
        start_time: float,
        status: ExecutionStatus,
        error_message: str
    ) -> None:
        execution_time_ms = self._elapsed_ms(start_time)
        tool_name = getattr(request, 'tool_name', 'unknown').strip().lower()

        _, audit_record = ExecutionResultFactory.failure(
            execution_id=request.execution_id,
            tool_name=tool_name,
            skill_name=request.skill_name,
            environment=request.environment,
            approved_by_human=request.approved_by_human,
            execution_time_ms=execution_time_ms,
            status=status,
            error_message=error_message
        )
        
        audit_logger.record(audit_record)

    def execute(self, skill: SkillDefinition, request: ToolExecutionRequest) -> ToolExecutionResult:
        start_time = time.perf_counter()

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
            tool_def = RegisteredToolRegistry.get(tool_name)
            SandboxGovernance.validate(skill, tool_def, request)

            # 6. Execute tool (Deterministic execution, no async)
            tool_output = runtime_tool.execute(request)
            
            # Validate output
            validate_tool_output(tool_output)

            execution_time_ms = self._elapsed_ms(start_time)
            
            if execution_time_ms > skill.execution_contract.constraints.max_execution_time_ms:
                raise RuntimeTimeoutError(
                    f"Tool execution exceeded maximum allowed time of "
                    f"{skill.execution_contract.constraints.max_execution_time_ms}ms"
                )

            result, audit_record = ExecutionResultFactory.success(
                execution_id=request.execution_id,
                tool_name=tool_name,
                skill_name=request.skill_name,
                environment=request.environment,
                approved_by_human=request.approved_by_human,
                execution_time_ms=execution_time_ms,
                output=tool_output.output
            )
            audit_logger.record(audit_record)
            return result

        except RuntimeTimeoutError as e:
            self._finalize_failure(
                request=request, start_time=start_time,
                status=ExecutionStatus.TIMEOUT,
                error_message=str(e)
            )
            raise e
        except RuntimeAuthorizationError as e:
            self._finalize_failure(
                request=request, start_time=start_time,
                status=ExecutionStatus.DENIED,
                error_message=str(e)
            )
            raise e
        except RuntimeGovernanceError as e:
            self._finalize_failure(
                request=request, start_time=start_time,
                status=ExecutionStatus.GOVERNANCE_REJECTED,
                error_message=str(e)
            )
            raise e
        except RuntimeExecutionError as e:
            self._finalize_failure(
                request=request, start_time=start_time,
                status=ExecutionStatus.FAILED,
                error_message=str(e)
            )
            raise e
        except Exception as e:
            internal_message = (
                f"Unhandled runtime failure: {type(e).__name__}"
            )
            
            self._finalize_failure(
                request=request, start_time=start_time,
                status=ExecutionStatus.FAILED,
                error_message=internal_message
            )
            raise RuntimeExecutionError(
                "Unhandled runtime execution failure"
            ) from e
