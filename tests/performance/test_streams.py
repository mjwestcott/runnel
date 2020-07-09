from datetime import datetime
from typing import List

import pytest
from faker import Faker

from runnel.compression import LZ4, Gzip
from runnel.hashing import fasthash, md5hash
from runnel.record import Record
from runnel.serialization import FastJSONSerializer, JSONSerializer

fake = Faker()


class Store(Record):
    id: int
    name: str

    @classmethod
    def random(cls):
        return cls(id=fake.pyint(), name=fake.catch_phrase())


class Item(Record):
    id: int
    name: str
    price: int
    currency: str
    store: Store

    @classmethod
    def random(cls):
        return cls(
            id=fake.pyint(),
            name=fake.word(),
            price=fake.pyint(),
            currency=fake.currency_code(),
            store=Store.random(),
        )


class Order(Record):
    id: int
    name: str
    user_id: int
    created_at: datetime
    shipped_at: datetime
    items: List[Item]

    @classmethod
    def random(cls, id=None):
        return cls(
            id=id or fake.pyint(),
            name=fake.sentence(),
            user_id=fake.pyint(),
            created_at=datetime.utcnow(),
            shipped_at=datetime.utcnow(),
            items=[Item.random() for _ in range(20)]
        )


record = Order.random()
default = (JSONSerializer, Gzip, md5hash)
fast = (FastJSONSerializer, LZ4, fasthash)


@pytest.mark.parametrize("config", [default, fast])
def test_serialize(benchmark, app, config):
    serializer, compressor, hasher = config
    stream = app.stream(
        name="orders",
        record=Order,
        partition_by=lambda o: o.name,
        serializer=serializer(compressor=compressor()),
        hasher=hasher,
    )

    def serialize(r):
        key = stream.route(stream._compute_key(r))
        value = stream.serialize(r)
        assert key and value

    benchmark(serialize, record)


@pytest.mark.parametrize("config", [default, fast])
def test_round_trip(benchmark, app, config):
    serializer, compressor, hasher = config
    stream = app.stream(
        name="orders",
        record=Order,
        partition_by=lambda o: o.name,
        serializer=serializer(compressor=compressor()),
        hasher=hasher,
    )

    def round_trip(r):
        stream.deserialize(stream.serialize(r))

    benchmark(round_trip, record)
