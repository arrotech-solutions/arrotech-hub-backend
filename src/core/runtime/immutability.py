from __future__ import annotations

import json
import math
from types import MappingProxyType
from typing import Any

MAX_PAYLOAD_DEPTH = 25


def _stable_json_repr(obj: Any) -> str:
    return json.dumps(
        _canonicalize_json(obj),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False
    )


def _canonicalize_json(obj: Any) -> Any:
    obj_type = type(obj)
    if obj_type in (dict, MappingProxyType):
        return {
            k: _canonicalize_json(v)
            for k, v in sorted(obj.items())
        }
    if obj_type in (list, tuple):
        return [
            _canonicalize_json(v)
            for v in obj
        ]
    if obj_type in (set, frozenset):
        normalized = [
            _canonicalize_json(v)
            for v in obj
        ]
        return sorted(
            normalized,
            key=_stable_json_repr
        )
    return obj


def freeze_structure(obj: Any) -> Any:
    """
    Recursively reconstructs ALL structures into immutable equivalents.

    SECURITY GUARANTEE:
    - Breaks aliasing
    - Prevents mutable leakage
    - Ensures deterministic structure identity
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
        rebuilt = {
            str(k): freeze_structure(v)
            for k, v in obj.items()
        }
        return MappingProxyType(rebuilt)

    if obj_type is MappingProxyType:
        rebuilt = {
            str(k): freeze_structure(v)
            for k, v in obj.items()
        }
        return MappingProxyType(rebuilt)

    if obj_type in (list, tuple):
        return tuple(freeze_structure(v) for v in obj)

    if obj_type in (set, frozenset):
        rebuilt = [freeze_structure(v) for v in obj]
        rebuilt.sort(key=_stable_json_repr)
        return tuple(rebuilt)

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

    obj_type = type(obj)

    if obj is None:
        return

    if obj_type in (str, int, bool):
        return

    if obj_type is float:
        if not math.isfinite(obj):
            raise ValueError(f"Non-finite float detected: {obj}")
        return

    obj_id = id(obj)

    if obj_id in visited:
        raise ValueError("Circular reference detected")

    if obj_type in (dict, MappingProxyType):
        visited.add(obj_id)

        try:
            for key, value in obj.items():
                if type(key) is not str:
                    raise ValueError(
                        "Dictionary keys must be EXACTLY str"
                    )

                validate_json_safe_payload(
                    value,
                    depth + 1,
                    visited
                )

        finally:
            visited.remove(obj_id)

        return

    if obj_type in (list, tuple, set, frozenset):
        visited.add(obj_id)

        try:
            for item in obj:
                validate_json_safe_payload(
                    item,
                    depth + 1,
                    visited
                )

        finally:
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
    obj_type = type(obj)
    if obj_type is MappingProxyType:
        return {k: thaw_structure(v) for k, v in obj.items()}
    elif obj_type is tuple:
        return [thaw_structure(v) for v in obj]
    elif obj_type is frozenset:
        return {thaw_structure(v) for v in obj}
    return obj
