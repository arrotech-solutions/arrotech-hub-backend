from typing import Union, Tuple, Dict, Any, TypeAlias

# Use a more explicit Union for Pydantic to avoid infinite recursion
# during schema generation in some environments.
ImmutableJSON: TypeAlias = Union[
    str, int, float, bool, None,
    Tuple[Any, ...],
    Dict[str, Any]
]
