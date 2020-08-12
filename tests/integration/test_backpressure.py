import asyncio
from itertools import count

import pytest

from runnel.record import Record
from tests.helpers.waiting import wait_done
from tests.helpers.worker import worker


class Action(Record, primitive=True):
    key: str
    seq: int


@pytest.mark.asyncio
async def test_backpressure(app, results):
    """
    Ensure that a single slow partition processor does not block others.
    """
    seq = count()
    keys = ["A", "B"]
    actions = app.stream(
        "actions",
        record=Action,
        partition_by="key",
        partition_count=2,
        hasher=lambda key: 0 if key == "A" else 1,
    )

    # Ensure that events are split between the two partitions.
    assert actions.route(keys[0]) != actions.route(keys[1])

    @app.processor(actions, prefetch_count=8)
    async def proc(events):
        async for action in events.records():
            assert action.key in keys
            if action.key == "A":
                await asyncio.sleep(10)
            await results.incr()

    async with worker(app):
        records = [Action(key="A" if i % 2 == 0 else "B", seq=next(seq)) for i in range(100)]
        await actions.send(*records)

        # The 50 odd numbered events should be read and processed by partition B,
        # even though A is very slow.
        await wait_done(results, count=50)
