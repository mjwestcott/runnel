import random
from itertools import count

from runnel import App
from runnel.record import Record
from tests.helpers.processes import subprocess
from tests.helpers.results import Results
from tests.helpers.waiting import event_id, wait_atleast

# At the module level because we will import it via the CLI from a subprocess.
app = App(
    name="tests.integration.test_recovery:app",
    default_partition_count=8,
    default_lock_expiry=1,
    default_grace_period=0.2,
    default_read_timeout=50,
    default_prefetch_count=4,
    default_assignment_sleep=0.2,
    default_join_delay=0,
)


class Action(Record, primitive=True):
    key: str
    seq: int


actions = app.stream("actions", record=Action, partition_by="key")


@app.processor(actions, lock_expiry=2)
async def proc(events):
    results = Results(app.redis)
    async for obj in events.records():
        await results.incr()
        await results.redis.incr(event_id(obj.seq))


async def test_recovery(results):
    """
    Ensure that a new worker can acquire the locks left over from the dead one and
    complete processing.
    """
    seq = count()
    bulk = 222
    keys = list("ABCDEFGHIJ")

    async def send():
        await actions.send(*[Action(key=random.choice(keys), seq=next(seq)) for _ in range(bulk)])

    # Kill a worker process ungracefully partway through processing. It will not be able
    # to publish its departure or release its locks.
    with subprocess(app.name, graceful=False):
        await send()
        await wait_atleast(results, delay=3, count=bulk // 4)

    with subprocess(app.name, graceful=True):
        # We cannot guarantee that events will be processed exactly once after a worker
        # has no chance to shutdown gracefully. It may have seen an event, but not yet
        # acknowledged it, so we check results >= expected.
        await send()
        await wait_atleast(results, count=bulk * 2, delay=6)
