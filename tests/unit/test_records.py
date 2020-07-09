from typing import Dict, List, Set

import pytest

from runnel.exceptions import Misconfigured
from runnel.record import Record


def test_misconfigured():
    class R1(Record):
        a: int
        b: float
        c: bool
        d: str
        e: bytes

    class R2(Record, primitive=True):
        a: int
        b: float
        c: bool
        d: str
        e: bytes

    class R3(Record):
        a: List[int]
        b: Set[str]
        c: Dict[str, float]

    with pytest.raises(Misconfigured):
        # yapf: disable
        class R4(Record, primitive=True):
            a: List[int]
            b: Set[str]
            c: Dict[str, float]


def test_nested():
    class Child(Record):
        a: int

    class Parent(Record):
        children: List[Child]

    record = Parent(children=[Child(a=1), Child(a=2)])
    assert record.dict() == {"children": [{"a": 1}, {"a": 2}]}
