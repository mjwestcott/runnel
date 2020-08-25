import random

import anyio
import pytest

from runnel import App
from runnel.record import Record
from tests.helpers.waiting import event_id, wait_done, wait_running
from tests.helpers.worker import workers


class Action(Record, primitive=True):
    key: int
    seq: int


@pytest.mark.slow
@pytest.mark.parametrize("n_workers", [1, 16])
async def test_many_partitions(results, n_workers):
    """
    Ensure that the system can handle 256 partitions (with 1 or many workers).
    """
    n_events = 2**10
    app = App(
        name="testapp-large",
        default_lock_expiry=8,
        default_grace_period=4,
        default_read_timeout=400,
        default_pool_size=2,
        default_join_delay=4,
    )
    actions = app.stream(
        "actions",
        record=Action,
        partition_by=lambda a: a.key,
        partition_count=256,
    )

    @app.processor(actions, prefetch_count=64)
    async def proc(events):
        async for action in events.records():
            await anyio.sleep(random.random())
            await results.incr()
            await results.redis.incr(event_id(action.seq))

    async with workers(app, count=n_workers) as ws:
        await wait_running(*ws, delay=16)
        await actions.send(*[Action(key=random.randint(0, 4096), seq=i) for i in range(n_events)])
        await wait_done(results, count=n_events, delay=16, debug_key=event_id)
