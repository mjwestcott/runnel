import pytest

from runnel.compression import LZ4, Gzip
from runnel.serialization import JSONSerializer
from tests.helpers.records import Order
from tests.helpers.waiting import wait_done
from tests.helpers.worker import worker


@pytest.mark.asyncio
@pytest.mark.parametrize("compressor", [Gzip(), LZ4()])
async def test_builtin(app, results, compressor):
    orders = app.stream(
        "orders",
        record=Order,
        partition_by="id",
        serializer=JSONSerializer(compressor=compressor),
    )

    @app.processor(orders)
    async def check(events):
        async for obj in events.records():
            assert isinstance(obj, Order)
            await results.incr()

    async with worker(app):
        await orders.send(*[Order.random() for _ in range(10)])
        await wait_done(results, count=10)
