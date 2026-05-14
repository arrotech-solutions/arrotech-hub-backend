from __future__ import annotations

from typing import TypeAlias
from types import MappingProxyType

ImmutableJSON: TypeAlias = (
    str
    | int
    | float
    | bool
    | None
    | tuple["ImmutableJSON", ...]
    | MappingProxyType
)
