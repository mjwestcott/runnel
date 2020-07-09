import random
from typing import List
from uuid import uuid4

from faker import Faker

from runnel.record import Record

fake = Faker()


class Reading(Record, primitive=True):
    id: int
    temperature: float
    measured: bool
    sensor: str
    uuid: bytes

    @classmethod
    def random(cls, id=None):
        return cls(
            id=id or fake.pyint(),
            temperature=fake.pyfloat(),
            measured=fake.pybool(),
            sensor=fake.word(),
            uuid=uuid4().bytes,
        )


class Item(Record):
    id: int
    name: str


class Order(Record):
    id: int
    name: str
    items: List[Item]

    @classmethod
    def random(cls, id=None):
        return cls(
            id=id or fake.pyint(),
            name=fake.word(),
            items=[  # yapf: disable
                Item(id=fake.pyint(), name=fake.word())
                for _ in range(random.randint(1, 10))
            ]
        )
