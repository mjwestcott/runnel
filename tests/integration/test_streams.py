import pytest

from runnel.record import Record
from tests.helpers.waiting import wait_done
from tests.helpers.worker import workers


class Action(Record, primitive=True):
    key: str
    seq: int


class Filtered(Record):
    key: str
    seq: int


@pytest.mark.asyncio
async def test_streams(app, results):
    keys = list("ABCDEFGHIJ")
    n_workers = 2
    n_events = 1_000
    n_per_key = n_events // len(keys)

    actions = app.stream("actions", record=Action, partition_by="key", partition_count=8)
    filtered = app.stream("filtered", record=Filtered, partition_by="key", partition_count=1)

    # First processor: filter events by key and send them to another stream.
    @app.processor(actions, prefetch_count=32)
    async def proc1(events):
        async for action in events.records():
            if action.key in {"A", "B"}:
                await filtered.send(Filtered(key=action.key, seq=action.seq))
            await results.incr()

    # Second processor: ensure that all events appear in order (increasing seq ids) per
    # partition key.
    @app.processor(filtered, prefetch_count=1)
    async def proc2(events):
        count = {"A": 0, "B": 0}
        last_seen = {"A": -1, "B": -1}

        async for record in events.records():
            assert record.key in {"A", "B"}
            assert count[record.key] < n_per_key
            assert record.seq > last_seen[record.key]

            count[record.key] += 1
            last_seen[record.key] = record.seq

    async with workers(app, count=n_workers):
        for i in range(n_per_key):
            await actions.send(*[Action(key=key, seq=i) for key in keys])
        await wait_done(results, count=n_events, delay=10)
