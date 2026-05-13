from typing import Any
from types import MappingProxyType

def freeze_structure(obj: Any) -> Any:
    """
    Recursively converts mutable structures into their immutable equivalents.
    dict -> MappingProxyType
    list -> tuple
    set -> frozenset
    """
    if isinstance(obj, dict):
        return MappingProxyType({k: freeze_structure(v) for k, v in obj.items()})
    elif isinstance(obj, (list, tuple)):
        return tuple(freeze_structure(v) for v in obj)
    elif isinstance(obj, (set, frozenset)):
        return frozenset(freeze_structure(v) for v in obj)
    return obj

def validate_json_safe_payload(obj: Any) -> None:
    """Issue 3: Reject all non-JSON-safe request payload objects."""
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return
    elif isinstance(obj, (dict, MappingProxyType)):
        for k, v in obj.items():
            if not isinstance(k, str):
                 raise ValueError(f"Request payload dictionary keys must be strings, got {type(k)}")
            validate_json_safe_payload(v)
    elif isinstance(obj, (list, tuple, set, frozenset)):
        for item in obj:
            validate_json_safe_payload(item)
    else:
        raise ValueError(f"Request payload contains forbidden type: {type(obj)}. Only basic JSON types allowed.")

def thaw_structure(obj: Any) -> Any:
    """
    Recursively converts immutable structures back into serialization-safe mutable equivalents.
    MappingProxyType/dict -> dict
    tuple/list -> list
    frozenset/set -> set
    """
    if isinstance(obj, (dict, MappingProxyType)):
        return {k: thaw_structure(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return list(thaw_structure(v) for v in obj)
    elif isinstance(obj, (set, frozenset)):
        return set(thaw_structure(v) for v in obj)
    return obj
