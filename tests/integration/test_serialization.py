import pytest

from runnel.exceptions import Misconfigured
from runnel.serialization import FastJSONSerializer, JSONSerializer
from tests.helpers.records import Order, Reading
from tests.helpers.waiting import wait_done
from tests.helpers.worker import worker


@pytest.mark.parametrize("serializer", [JSONSerializer(), FastJSONSerializer()])
async def test_builtin(app, results, serializer):
    orders = app.stream(
        "orders",
        record=Order,
        partition_by="id",
        serializer=serializer,
    )

    @app.processor(orders)
    async def check(events):
        async for obj in events.records():
            assert isinstance(obj, Order)
            await results.incr()

    async with worker(app):
        await orders.send(*[Order.random() for _ in range(10)])
        await wait_done(results, count=10)


async def test_primitive(app, results):
    with pytest.raises(Misconfigured):
        # Cannot serialize primitive records.
        app.stream(
            "readings",
            record=Reading,
            partition_by="id",
            serializer=JSONSerializer(),
        )
