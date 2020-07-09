import random
from itertools import count

import anyio
import pytest

from runnel.constants import ExceptionPolicy
from runnel.record import Record
from tests.helpers.waiting import event_id, wait_done
from tests.helpers.worker import worker


class Action(Record, primitive=True):
    key: str
    seq: int


@pytest.mark.asyncio
async def test_policy_halt(app, results):
    seq = count()
    keys = list("ABCDEFGHIJ")
    actions = app.stream("actions", record=Action, partition_by="key")
    await actions.send(*[Action(key=random.choice(keys), seq=next(seq)) for _ in range(100)])

    @app.processor(actions, exception_policy=ExceptionPolicy.HALT, grace_period=0.1)
    async def proc(events):
        async for obj in events.records():
            if obj.seq == 10:
                raise ValueError("testing-user-error")

    with pytest.raises(ValueError):
        async with worker(app):
            await anyio.sleep(1)


@pytest.mark.asyncio
async def test_policy_quarantine(app, results):
    seq = count()
    keys = ["A", "B"]
    actions = app.stream("actions", record=Action, partition_by="key", partition_count=2)

    # Ensure that events are split between the two partitions.
    assert actions.route(keys[0]) != actions.route(keys[1])

    @app.processor(actions, exception_policy=ExceptionPolicy.QUARANTINE)
    async def proc(events):
        async for obj in events.records():
            await results.incr()
            await results.redis.incr(event_id(obj.seq))
            if obj.seq == 55:
                raise ValueError("testing-user-error")

    async with worker(app):
        records = [Action(key="A" if i % 2 == 0 else "B", seq=next(seq)) for i in range(100)]
        await actions.send(*records)

        # Until seq=55, all events succeed. Then the partition containing key B is
        # poisoned, so only half the remaining succeed.
        await wait_done(results, count=55 + (45 // 2), debug_key=event_id)


@pytest.mark.asyncio
async def test_policy_ignore(app, results):
    seq = count()
    keys = list("ABCDEFGHIJ")
    actions = app.stream("actions", record=Action, partition_by="key")
    await actions.send(*[Action(key=random.choice(keys), seq=next(seq)) for _ in range(100)])

    @app.processor(actions, exception_policy=ExceptionPolicy.IGNORE)
    async def proc(events):
        async for obj in events.records():
            await results.incr()
            await results.redis.incr(event_id(obj.seq))
            if obj.seq == 10:
                raise ValueError("testing-user-error")

    async with worker(app):
        await wait_done(results, count=100, debug_key=event_id)
