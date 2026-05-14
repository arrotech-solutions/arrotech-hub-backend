import math
from .exceptions import RuntimeExecutionError

MAX_OUTPUT_DEPTH = 25


def _validate_json_safe(
    obj: any,
    depth: int = 0,
    visited: set[int] | None = None
) -> None:

    if visited is None:
        visited = set()

    if depth > MAX_OUTPUT_DEPTH:
        raise RuntimeExecutionError(
            f"Tool output exceeds maximum depth of {MAX_OUTPUT_DEPTH}"
        )

    obj_id = id(obj)

    if obj_id in visited:
        raise RuntimeExecutionError(
            "Circular reference detected in tool output"
        )

    obj_type = type(obj)

    if obj is None:
        return

    if obj_type in (str, int, bool):
        return

    if obj_type is float:
        if not math.isfinite(obj):
            raise RuntimeExecutionError(
                f"Non-finite float detected: {obj}"
            )
        return

    if obj_type is dict:

        visited.add(obj_id)

        try:
            for key, value in obj.items():

                if type(key) is not str:
                    raise RuntimeExecutionError(
                        "Tool output keys must be EXACTLY str"
                    )

                _validate_json_safe(
                    value,
                    depth + 1,
                    visited
                )

        finally:
            visited.remove(obj_id)

        return

    if obj_type is list:

        visited.add(obj_id)

        try:
            for item in obj:

                _validate_json_safe(
                    item,
                    depth + 1,
                    visited
                )

        finally:
            visited.remove(obj_id)

        return

    raise RuntimeExecutionError(
        f"Invalid output type detected: {obj_type}"
    )


def validate_tool_output(output: any) -> None:
    """
    Validates that tool output is JSON-safe and bounded.
    """
    # Risk 6: Replace isinstance with exact type match
    if type(output) is not dict:
        raise RuntimeExecutionError(f"Tool output must be EXACTLY a dictionary, got {type(output)}")
    
    _validate_json_safe(output)
