import json
import random
from itertools import count

import pytest

from runnel.constants import ExceptionPolicy
from runnel.middleware import DeadLetterMiddleware
from runnel.record import Record
from tests.helpers.waiting import wait_done
from tests.helpers.worker import worker


@pytest.mark.asyncio
@pytest.mark.parametrize("primitive", [True, False])
async def test_middleware(app, results, primitive):
    class Action(Record, primitive=primitive):
        key: str
        seq: int

    seq = count()
    keys = list("ABCDEFGHIJ")

    actions = app.stream("actions", record=Action, partition_by="key")
    await actions.send(*[Action(key=random.choice(keys), seq=next(seq)) for _ in range(100)])
    dead_letter = DeadLetterMiddleware(source=actions)

    @app.processor(actions, exception_policy=ExceptionPolicy.IGNORE, middleware=[dead_letter])
    async def proc(events):
        async for event in events:
            obj = actions.deserialize(event.data)
            if obj.seq == 11:
                raise ValueError("testing-user-error")

    @app.processor(dead_letter.sink)
    async def dead(events):
        async for event in events:
            if primitive == True:
                assert actions.deserialize(event.data).seq == 11
            else:
                assert json.loads(dead_letter.sink.deserialize(event.data).data)["seq"] == 11
            await results.incr()

    async with worker(app):
        await wait_done(results, count=1)


@pytest.mark.asyncio
async def test_middleware_batches(app, results):
    class Action(Record, primitive=True):
        key: str
        seq: int

    seq = count()
    keys = list("ABCDEFGHIJ")
    batch_size = 10

    actions = app.stream("actions", record=Action, partition_by="key", partition_count=1)
    await actions.send(*[Action(key=random.choice(keys), seq=next(seq)) for _ in range(100)])
    dead_letter = DeadLetterMiddleware(source=actions)

    @app.processor(
        actions,
        exception_policy=ExceptionPolicy.IGNORE,
        middleware=[dead_letter],
        prefetch_count=10,
    )
    async def proc(events):
        async for batch in events.take(batch_size, within=0.1):
            for event in batch:
                obj = actions.deserialize(event.data)
                if obj.seq == 11:
                    raise ValueError("testing-user-error")
                    # The entire batch has failed, all 10 events sent to the dead-letter queue.

    @app.processor(dead_letter.sink)
    async def dead(events):
        async for event in events:
            assert isinstance(actions.deserialize(event.data).seq, int)
            await results.incr()

    async with worker(app):
        await wait_done(results, count=batch_size)
