from src.core.skills.contracts import RegisteredToolRegistry
from src.core.runtime.registry import runtime_registry
from src.core.runtime.audit import audit_logger
from src.core.runtime.version import RUNTIME_VERSION
from src.core.runtime.requests import ToolExecutionRequest
from src.core.runtime.results import ToolOutput

import inspect
from typing import get_type_hints, Any
from src.core.skills.models import EnvironmentScope

def _is_recursively_immutable(obj: Any) -> bool:
    """Issue 6: Recursive immutability inspection."""
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return True
    if isinstance(obj, (tuple, frozenset)):
        return all(_is_recursively_immutable(item) for item in obj)
    if callable(obj):
        return True
    return False

def validate_tool_statelessness(tool: any) -> None:
    allowed_attributes = {
        'name', 'requires_shell', 'requires_network', 'mutates_files', 
        'deterministic', 'allowed_environments', 'execute'
    }
    
    if hasattr(tool, '__dict__'):
        for attr in tool.__dict__:
            if attr not in allowed_attributes and not attr.startswith('__'):
                if not _is_recursively_immutable(tool.__dict__[attr]):
                    raise SystemExit(f"Runtime validation failed: Tool '{tool.name}' has illegal mutable state attribute '{attr}'")
                
    # Class-level recursive statelessness (Issue 6)
    for name, value in inspect.getmembers(tool.__class__):
        if not name.startswith('__') and name not in allowed_attributes:
            if not _is_recursively_immutable(value):
                raise SystemExit(f"Runtime validation failed: Tool '{tool.name}' class '{tool.__class__.__name__}' has illegal mutable class variable '{name}'")

def validate_output_contract(model_class: any) -> None:
    """Issue 10: Verify ToolOutput contract immutability."""
    if not hasattr(model_class, "model_config"):
        raise SystemExit(f"Runtime validation failed: {model_class.__name__} is not a valid Pydantic model.")
        
    config = model_class.model_config
    if not config.get("frozen"):
        raise SystemExit(f"Runtime validation failed: {model_class.__name__} must be frozen.")
    if config.get("extra") != "forbid":
        raise SystemExit(f"Runtime validation failed: {model_class.__name__} must forbid extra fields.")
        
    fields = model_class.model_fields
    required = {"status", "output", "error_message"}
    for field in required:
        if field not in fields:
             raise SystemExit(f"Runtime validation failed: {model_class.__name__} is missing required field '{field}'.")

def validate_runtime_integrity() -> None:
    """Validates the governed execution substrate prior to accepting requests."""
    
    if not RUNTIME_VERSION:
        raise SystemExit("Runtime validation failed: RUNTIME_VERSION missing.")
        
    if audit_logger is None:
        raise SystemExit("Runtime validation failed: Audit logger not initialized.")
        
    gov_tools = RegisteredToolRegistry.all()
    run_tools = runtime_registry.all()
    
    for name in run_tools.keys():
        if not RegisteredToolRegistry.exists(name):
            raise SystemExit(f"Runtime validation failed: Runtime tool '{name}' has no governance definition.")
            
    for name, tool_def in gov_tools.items():
        run_tool = run_tools.get(name)
        if not run_tool:
            raise SystemExit(f"Runtime validation failed: Governance tool '{name}' has no runtime implementation.")
            
        validate_tool_statelessness(run_tool)
        
        # Strict Signature Validation (Issue 3)
        sig = inspect.signature(run_tool.execute)
        hints = get_type_hints(run_tool.execute)
        
        params = list(sig.parameters.values())
        if len(params) != 1:
            raise SystemExit(f"Runtime validation failed: Tool '{name}' execute method must take exactly 1 parameter (request)")
        
        param = params[0]
        if param.name != "request":
            raise SystemExit(f"Runtime validation failed: Tool '{name}' execute parameter must be named 'request'")
            
        if hints.get('request') != ToolExecutionRequest:
            raise SystemExit(f"Runtime validation failed: Tool '{name}' execute 'request' parameter must be annotated as ToolExecutionRequest")
            
        if hints.get('return') != ToolOutput:
            raise SystemExit(f"Runtime validation failed: Tool '{name}' execute return must be annotated as ToolOutput")
            
        # ToolOutput contract validation (Issue 10)
        validate_output_contract(ToolOutput)
            
        if not tool_def.deterministic:
            raise SystemExit(f"Runtime validation failed: Tool '{name}' is explicitly non-deterministic.")
            
        # Strict Attribute Type Validation (Issue 9)
        required_types = {
            "name": str,
            "requires_shell": bool,
            "requires_network": bool,
            "mutates_files": bool,
            "deterministic": bool,
            "allowed_environments": list
        }
        
        for attr, expected_type in required_types.items():
            val = getattr(run_tool, attr, None)
            if not isinstance(val, expected_type):
                raise SystemExit(f"Runtime validation failed: Tool '{name}' attribute '{attr}' must be of type {expected_type.__name__}")

        if not run_tool.allowed_environments:
            raise SystemExit(f"Runtime validation failed: Tool '{name}' allowed_environments list cannot be empty.")
            
        for env in run_tool.allowed_environments:
            if not isinstance(env, EnvironmentScope):
                raise SystemExit(f"Runtime validation failed: Tool '{name}' has invalid environment type in allowed_environments.")
            
        if tool_def.requires_shell != run_tool.requires_shell:
            raise SystemExit(f"Runtime validation failed: Tool '{name}' requires_shell mismatch.")
        if tool_def.requires_network != run_tool.requires_network:
            raise SystemExit(f"Runtime validation failed: Tool '{name}' requires_network mismatch.")
        if tool_def.mutates_files != run_tool.mutates_files:
            raise SystemExit(f"Runtime validation failed: Tool '{name}' mutates_files mismatch.")
        if tool_def.deterministic != run_tool.deterministic:
            raise SystemExit(f"Runtime validation failed: Tool '{name}' deterministic mismatch.")
        if set(tool_def.allowed_environments) != set(run_tool.allowed_environments):
            raise SystemExit(f"Runtime validation failed: Tool '{name}' allowed_environments mismatch.")
