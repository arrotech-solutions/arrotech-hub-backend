from __future__ import annotations
from typing import Union, Tuple, Any
from types import MappingProxyType
from pydantic import BaseModel, ConfigDict
import sys

# Set recursion limit higher just in case
sys.setrecursionlimit(2000)

try:
    ImmutableJSON = Union[
        str,
        int,
        float,
        bool,
        None,
        Tuple['ImmutableJSON', ...],
        MappingProxyType
    ]

    class TestModel(BaseModel):
        data: ImmutableJSON
        model_config = ConfigDict(arbitrary_types_allowed=True)

    m = TestModel(data=("a", ("b", None)))
    print("Success!")
    print(m.model_dump())
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
