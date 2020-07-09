import random

import pytest

from runnel.record import Record
from tests.helpers.waiting import event_id, wait_done, wait_running
from tests.helpers.worker import worker, workers


class Action(Record, primitive=True):
    key: str
    seq: int


@pytest.mark.asyncio
async def test_simple(app, results):
    n_events = 10
    actions = app.stream(
        "actions",
        record=Action,
        partition_by=lambda a: a.key,
        partition_count=2,
    )

    keys = list("ABCDEFGHIJ")
    await actions.send(*[Action(key=random.choice(keys), seq=i) for i in range(n_events)])

    @app.processor(actions)
    async def proc(events):
        async for action in events.records():
            assert action.key in keys
            await results.incr()
            await results.redis.incr(event_id(action.seq))

    async with worker(app) as w:
        await wait_running(w)
        await wait_done(results, count=n_events, delay=10, debug_key=event_id)


@pytest.mark.asyncio
@pytest.mark.parametrize("partition_count", [1, 8])
@pytest.mark.parametrize("prefetch_count", [1, 50])
@pytest.mark.parametrize("batch_size", [1, 24])
@pytest.mark.parametrize("n_events", [333])
@pytest.mark.parametrize("n_workers", [1, 3])
async def test_app(
    app,
    results,
    partition_count,
    prefetch_count,
    batch_size,
    n_events,
    n_workers,
):
    actions = app.stream(
        "actions",
        record=Action,
        partition_by=lambda a: a.key,
        partition_count=partition_count,
    )

    keys = list("ABCDEFGHIJ")
    await actions.send(*[Action(key=random.choice(keys), seq=i) for i in range(n_events)])

    @app.processor(
        actions,
        lock_expiry=2,
        assignment_sleep=1,
        prefetch_count=prefetch_count,
    )
    async def proc(events):
        if batch_size == 1:
            async for action in events.records():
                assert action.key in keys
                await results.incr()
                await results.redis.incr(event_id(action.seq))
        else:
            async for batch in events.take(batch_size, within=0.1).records():
                assert len(batch) <= batch_size
                for action in batch:
                    assert action.key in keys
                    await results.incr()
                    await results.redis.incr(event_id(action.seq))

    async with workers(app, count=n_workers) as ws:
        await wait_running(*ws)
        await wait_done(results, count=n_events, delay=10, debug_key=event_id)
