from typing import Union, Mapping

# Issue 1: Strict Immutable JSON Type Contract
# Enforced recursively via validate_json_safe_payload()
# Non-recursive Union used to prevent Pydantic collection errors in Python 3.10.
ImmutableJSON = Union[
    str,
    int,
    float,
    bool,
    None,
    tuple,
    Mapping
]
