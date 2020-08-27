import pytest

from tests.helpers.records import Order


@pytest.fixture
def stream(app):
    return app.stream(
        name="teststream",
        record=Order,
        partition_by="id",
        partition_count=1,
    )


async def _read(stream):
    assert stream.partition_count == 1
    key = stream.partition_key(0)
    results = await stream.app.redis.xread(**{key: "0-0"})
    for stream, result in results.items():
        return result


async def test_send(stream):
    await stream.send(Order.random())
    assert len(await _read(stream)) == 1


async def test_sendmany(stream):
    await stream.send(*[Order.random() for _ in range(10)])
    assert len(await _read(stream)) == 10


async def test_sendmany_with_ids(stream):
    orders = [Order.random() for _ in range(3)]
    stream_ids = ["1-1", "1-2", "1-3"]
    await stream.send(*orders, stream_ids=stream_ids)

    found = [result[0].decode("utf-8") for result in await _read(stream)]
    assert found == stream_ids
