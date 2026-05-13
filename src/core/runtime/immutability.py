from __future__ import annotations

import math
from types import MappingProxyType
from typing import Any

MAX_PAYLOAD_DEPTH = 25


def freeze_structure(obj: Any) -> Any:
    """
    Recursively deep-copies and freezes structures.
    MUST break aliasing completely.
    """

    obj_type = type(obj)

    if obj is None:
        return None

    if obj_type in (str, int, bool):
        return obj

    if obj_type is float:
        if not math.isfinite(obj):
            raise ValueError(f"Non-finite float detected: {obj}")
        return obj

    if obj_type is dict:
        return MappingProxyType({
            str(k): freeze_structure(v)
            for k, v in obj.items()
        })

    if obj_type in (list, tuple):
        return tuple(
            freeze_structure(v)
            for v in obj
        )

    if obj_type in (set, frozenset):
        return frozenset(
            freeze_structure(v)
            for v in obj
        )

    if obj_type is MappingProxyType:
        return MappingProxyType({
            str(k): freeze_structure(v)
            for k, v in obj.items()
        })

    raise ValueError(
        f"Unsupported immutable conversion type: {obj_type}"
    )


def validate_json_safe_payload(
    obj: Any,
    depth: int = 0,
    visited: set[int] | None = None
) -> None:

    if visited is None:
        visited = set()

    if depth > MAX_PAYLOAD_DEPTH:
        raise ValueError(
            f"Payload exceeds maximum depth of {MAX_PAYLOAD_DEPTH}"
        )

    obj_id = id(obj)

    if obj_id in visited:
        raise ValueError(
            "Circular reference detected in payload"
        )

    obj_type = type(obj)

    if obj is None:
        return

    if obj_type in (str, int, bool):
        return

    if obj_type is float:
        if not math.isfinite(obj):
            raise ValueError(
                f"Non-finite float detected: {obj}"
            )
        return

    if obj_type in (dict, MappingProxyType):
        visited.add(obj_id)

        for key, value in obj.items():
            if type(key) is not str:
                raise ValueError(
                    f"Payload keys must be EXACTLY str, got {type(key)}"
                )

            validate_json_safe_payload(
                value,
                depth + 1,
                visited
            )

        visited.remove(obj_id)
        return

    if obj_type in (list, tuple, set, frozenset):
        visited.add(obj_id)

        for item in obj:
            validate_json_safe_payload(
                item,
                depth + 1,
                visited
            )

        visited.remove(obj_id)
        return

    raise ValueError(
        f"Forbidden payload type: {obj_type}"
    )


def thaw_structure(obj: Any) -> Any:
    """
    Recursively converts immutable structures back into mutable equivalents.
    Useful for tool input preparation where tools expect standard dicts/lists.
    """
    if isinstance(obj, MappingProxyType):
        return {k: thaw_structure(v) for k, v in obj.items()}
    elif isinstance(obj, tuple):
        return [thaw_structure(v) for v in obj]
    elif isinstance(obj, frozenset):
        return {thaw_structure(v) for v in obj}
    return obj
