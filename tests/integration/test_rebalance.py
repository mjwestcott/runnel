import random
from itertools import count

import pytest

from runnel.record import Record
from tests.helpers.waiting import event_id, wait_done, wait_running
from tests.helpers.worker import worker


class Action(Record, primitive=True):
    key: str
    seq: int


@pytest.mark.asyncio
@pytest.mark.parametrize("batch_size", [1, 11])
async def test_sequential(app, results, batch_size):
    seq = count()
    bulk = 33
    keys = list("ABCDEFGHIJ")
    actions = app.stream("actions", record=Action, partition_by="key")

    async def send():
        await actions.send(*[Action(key=random.choice(keys), seq=next(seq)) for _ in range(bulk)])

    @app.processor(actions, grace_period=1, assignment_sleep=0.3)
    async def proc(events):
        if batch_size == 1:
            async for obj in events.records():
                await results.incr()
                await results.redis.incr(event_id(obj.seq))
        else:
            async for batch in events.take(batch_size, within=0.1).records():
                for obj in batch:
                    await results.incr()
                    await results.redis.incr(event_id(obj.seq))

    # Add one worker at a time, then remove one worker at a time, waiting
    # for rebalances to complete each iteration.
    async with worker(app) as w1:
        await wait_running(w1)
        async with worker(app) as w2:
            await wait_running(w1, w2)
            async with worker(app) as w3:
                await wait_running(w1, w2, w3)
                async with worker(app) as w4:
                    await wait_running(w1, w2, w3, w4)
                    await send()

                    # Ensure existing events are processed before killing workers.
                    await wait_done(results, count=bulk, delay=4, debug_key=event_id)

                await wait_running(w1, w2, w3)
            await wait_running(w1, w2)
        await wait_running(w1)
        await send()

        # Ensure all events are processed once.
        await wait_done(results, count=bulk * 2, delay=8, debug_key=event_id)
