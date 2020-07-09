from typing import Dict, List

from runnel.record import Record
from runnel.serialization import default


def test_primitive(app):
    class R(Record, primitive=True):
        a: int
        b: float
        c: bool
        d: str
        e: bytes

    s = app.stream("s", record=R, partition_by="a")
    r = R(a=1, b=0.5, c=False, d="x", e=b"x")

    assert s.serialize(r) == {b"a": 1, b"b": 0.5, b"c": False, b"d": "x", b"e": b"x"}
    assert s.deserialize(s.serialize(r)) == r

    # The redis client will convert primitive data types to a bytes represenation,
    # which we will read back from the stream in the following format.
    response = {b"a": b"1", b"b": b"0.5", b"c": b"False", b"d": "x", b"e": b"x"}
    assert s.deserialize(response) == r


def test_complex1(app):
    class R(Record):
        a: int
        b: float
        c: bool
        d: str

    s = app.stream("s", record=R, partition_by="a", serializer=default)
    r = R(a=1, b=0.5, c=True, d="x")

    # Complex data types are serialized to a single 'data' field as JSON bytes
    # by default.
    assert s.serialize(r) == {b"data": b'{"a":1,"b":0.5,"c":true,"d":"x"}'}
    assert s.deserialize(s.serialize(r)) == r


def test_complex2(app):
    class R(Record):
        a: List[int]
        b: Dict[str, float]

    s = app.stream("s", record=R, partition_by="a", serializer=default)
    r = R(a=[1], b={"y": 0.5})

    assert s.serialize(r) == {b"data": b'{"a":[1],"b":{"y":0.5}}'}
    assert s.deserialize(s.serialize(r)) == r


def test_complex3(app):
    class Child(Record):
        a: int

    class Parent(Record):
        a: int
        children: List[Child]

    s = app.stream("s", record=Parent, partition_by="a", serializer=default)
    p = Parent(a=1, children=[Child(a=1), Child(a=2)])

    assert s.serialize(p) == {b"data": b'{"a":1,"children":[{"a":1},{"a":2}]}'}
    assert s.deserialize(s.serialize(p)) == p
