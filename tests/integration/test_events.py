import pytest

from runnel.types import Event
from tests.helpers.records import Order, Reading
from tests.helpers.waiting import wait_done
from tests.helpers.worker import worker


@pytest.mark.parametrize("want", ["raw", "records"])
async def test_single_primitive(app, results, want):
    readings = app.stream("readings", record=Reading, partition_by="id")
    await readings.send(*[Reading.random() for _ in range(2)])

    @app.processor(readings)
    async def proc(events):
        if want == "raw":
            async for event in events:
                assert isinstance(event, Event)
                await results.incr()
        elif want == "records":
            async for obj in events.records():
                assert isinstance(obj, Reading)
                await results.incr()

    async with worker(app):
        await wait_done(results, count=2)


@pytest.mark.parametrize("want", ["raw", "records"])
async def test_single_complex(app, results, want):
    orders = app.stream("orders", record=Order, partition_by="id")
    await orders.send(*[Order.random() for _ in range(2)])

    @app.processor(orders)
    async def proc(events):
        if want == "raw":
            async for event in events:
                assert isinstance(event, Event)
                await results.incr()
        elif want == "records":
            async for obj in events.records():
                assert isinstance(obj.id, int)
                assert isinstance(obj.items, list)
                await results.incr()

    async with worker(app):
        await wait_done(results, count=2)


@pytest.mark.parametrize("want", ["raw", "records"])
async def test_batch_primitive(app, results, want):
    readings = app.stream("readings", record=Reading, partition_by="id", partition_count=1)
    await readings.send(*[Reading.random() for _ in range(4)])

    @app.processor(readings)
    async def proc(events):
        if want == "raw":
            async for batch in events.take(2, within=0.1):
                assert len(batch) == 2
                for event in batch:
                    assert isinstance(event, Event)
                    await results.incr()
        elif want == "records":
            async for batch in events.take(2, within=0.1).records():
                assert len(batch) == 2
                for obj in batch:
                    assert isinstance(obj, Reading)
                    await results.incr()

    async with worker(app):
        await wait_done(results, count=4)


@pytest.mark.parametrize("want", ["raw", "records"])
async def test_batch_complex(app, results, want):
    orders = app.stream("orders", record=Order, partition_by="id", partition_count=1)
    await orders.send(*[Order.random() for _ in range(4)])

    @app.processor(orders)
    async def proc(events):
        if want == "raw":
            async for batch in events.take(2, within=0.1):
                assert len(batch) == 2
                for event in batch:
                    assert isinstance(event, Event)
                    await results.incr()
        elif want == "records":
            async for batch in events.take(2, within=0.1).records():
                assert len(batch) == 2
                for obj in batch:
                    assert isinstance(obj.id, int)
                    assert isinstance(obj.items, list)
                    await results.incr()

    async with worker(app):
        await wait_done(results, count=4)
