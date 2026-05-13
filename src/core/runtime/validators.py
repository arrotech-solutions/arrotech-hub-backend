import json
import math
from .results import ToolOutput
from .status import ExecutionStatus
from .exceptions import RuntimeExecutionError

MAX_TOOL_OUTPUT_BYTES = 1024 * 1024
MAX_OUTPUT_DEPTH = 25

def _validate_json_safe(obj: any, depth: int = 0) -> None:
    if depth > MAX_OUTPUT_DEPTH:
        raise RuntimeExecutionError(f"Tool output exceeds maximum depth of {MAX_OUTPUT_DEPTH}")
        
    if isinstance(obj, float):
        if not math.isfinite(obj):
            raise RuntimeExecutionError(f"Tool output contains non-finite float: {obj}")
        return
    if type(obj) in (str, int, bool, type(None)):
        return
    elif isinstance(obj, dict):
        for k, v in obj.items():
            if not isinstance(k, str):
                raise RuntimeExecutionError(f"Tool output dictionary keys must be strings, got {type(k)}")
            _validate_json_safe(v, depth + 1)
    elif isinstance(obj, list):
        for item in obj:
            _validate_json_safe(item, depth + 1)
    else:
        raise RuntimeExecutionError(f"Tool output contains invalid type: {type(obj)}. Only JSON-safe types are allowed.")

def validate_tool_output(output: ToolOutput) -> None:
    if output is None:
        raise RuntimeExecutionError("Tool output cannot be None")
    
    if not isinstance(output.output, dict):
        raise RuntimeExecutionError("Tool output payload must be a dictionary")

    if output.status not in (ExecutionStatus.SUCCESS, ExecutionStatus.FAILED):
        raise RuntimeExecutionError(f"Tool returned forbidden status '{output.status.value}'. Tools may only return SUCCESS or FAILED.")
        
    if output.status != ExecutionStatus.SUCCESS:
        if not output.error_message:
            raise RuntimeExecutionError("error_message is required when status is not SUCCESS")
    else:
        if output.error_message:
            raise RuntimeExecutionError("error_message is forbidden when status is SUCCESS")
            
    _validate_json_safe(output.output)
            
    # Output Size Governance
    output_size = len(json.dumps(output.output, separators=(',', ':')).encode('utf-8'))
    if output_size > MAX_TOOL_OUTPUT_BYTES:
        raise RuntimeExecutionError(f"Tool output exceeds maximum size of {MAX_TOOL_OUTPUT_BYTES} bytes (actual: {output_size} bytes)")
