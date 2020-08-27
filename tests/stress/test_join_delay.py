import random

import anyio
import pytest

from runnel import App
from runnel.record import Record
from tests.helpers.waiting import event_id, wait_done
from tests.helpers.worker import workers


class Action(Record, primitive=True):
    key: int
    seq: int


@pytest.mark.slow
async def test_no_join_delay(results):
    """
    With no join delay, the first executor to join will acquire all partitions and then
    all others will spend considerable time waiting to rebalance. Nonetheless, it should
    eventually succeed.
    """
    n_workers = 16
    n_partitions = 256
    n_events = 2**10
    app = App(
        name="testapp-large",
        default_lock_expiry=8,
        default_grace_period=4,
        default_read_timeout=400,
        default_pool_size=8,
        default_join_delay=0,
    )
    actions = app.stream(
        "actions",
        record=Action,
        partition_by=lambda a: a.key,
        partition_count=n_partitions,
    )

    @app.processor(actions, prefetch_count=24)
    async def proc(events):
        async for action in events.records():
            await anyio.sleep(random.random())
            await results.incr()
            await results.redis.incr(event_id(action.seq))

    async with workers(app, count=n_workers):
        await actions.send(*[Action(key=random.randint(0, 4096), seq=i) for i in range(n_events)])
        await wait_done(results, count=n_events, delay=32, debug_key=event_id)
