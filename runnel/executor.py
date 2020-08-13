import json
import random
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Dict, Set

import anyio
import structlog

from runnel.constants import Rebalance
from runnel.context import executor_id, stream
from runnel.exceptions import (
    AcquirePartitionLockFailed,
    ExtendPartitionLockFailed,
    NoPartitionsAssigned,
    RebalanceFailed,
)
from runnel.runner import Runner
from runnel.types import Partition

if TYPE_CHECKING:
    from runnel.processor import Processor

logger = structlog.get_logger(__name__)


@dataclass
class Executor:
    """
    This object is responsible for executing the user-provided processor function. It
    expects to join a distributed set of other executors and coordinates ownership
    over a subset of Redis stream partitions.
    """
    id: str
    processor: "Processor"
    partitions: Dict[int, Partition] = field(default_factory=dict)
    cond: anyio.abc.Condition = field(default_factory=anyio.create_condition)
    assigned: Set[Partition] = None
    owned: Set[Partition] = field(default_factory=set)
    poisoned: Set[Partition] = field(default_factory=set)

    def __post_init__(self):
        for i in range(self.stream.partition_count):
            self.partitions[i] = Partition(stream=self.stream, number=i)

    def __hash__(self):
        return hash((self.processor.name, self.id))

    @property
    def app(self):
        return self.processor.app

    @property
    def stream(self):
        return self.processor.stream

    @property
    def group(self):
        return self.processor.group

    @property
    def consumer(self):
        return self.processor.consumer

    @property
    def lock_expiry(self):
        return self.processor.lock_expiry

    def redis_lock_key(self, i):
        return self.processor.lock_key(i)

    @property
    def safe_partitions(self):
        return self.owned - self.poisoned - self.need_release

    @property
    def need_release(self):
        return self.owned - (self.assigned or set())

    @property
    def need_acquire(self):
        return (self.assigned or set()) - self.owned

    @property
    def rebalanced(self):
        return self.owned == self.assigned

    async def set_assigned(self, partitions: Set):
        async with self.cond:
            self.assigned = partitions
            await self.cond.notify_all()

    async def set_owned(self, partitions: Set):
        async with self.cond:
            self.owned = partitions
            await self.cond.notify_all()

    async def wait_for(self, fn=None, attr=None, value=None):
        if not fn:
            fn = lambda: getattr(self, attr) == value

        async with self.cond:
            while not fn():
                await self.cond.wait()

    @asynccontextmanager
    async def run_locks(self, partitions):
        for p in partitions:
            await p.lock.acquire()
        try:
            yield
        finally:
            for p in partitions:
                await p.lock.release()

    async def start(self):
        try:
            executor_id.set(self.id)
            stream.set(self.stream.name)
            await self._beat()
            await self.processor.maybe_join(self.id)
            await anyio.sleep(self.processor.join_delay)
            logger.info("executor-start")

            async with anyio.create_task_group() as tg:
                await tg.spawn(self.heartbeat)
                await tg.spawn(self.maintenance)
                await tg.spawn(self.control)
                await tg.spawn(Runner(self).run)
        finally:
            # Ensure that our partition locks are released and our departure is
            # broadcast to other workers.
            await self.release(set(self.owned), suppress_cancelled=True)
            await self.processor.maybe_leave(self.id)
            logger.critical("executor-exit")

    async def heartbeat(self):
        while True:
            await self._beat()
            await self.extend()
            await anyio.sleep(self.processor.lock_expiry / 4)

    async def _beat(self):
        logger.debug("beating")
        px = self.processor.lock_expiry * 1000
        await self.app.redis.set(self.processor.heartbeat_key(self.id), "beat", px=px)

    async def maintenance(self):
        while True:
            logger.info("maintenance")
            await self.processor.reap()
            jitter = self.processor.lock_expiry / 2 * random.random() + 1
            await anyio.sleep(jitter)

    async def control(self):
        send_stream, receive_stream = anyio.create_memory_object_stream()
        async with anyio.create_task_group() as tg:
            await tg.spawn(self._message_listener, send_stream)
            await tg.spawn(self._message_consumer, receive_stream)

    async def _message_listener(self, send_stream):
        async for msg in self.processor.read_control_messages():
            if msg and msg[b"reason"].decode("utf-8") in set(Rebalance):
                logger.debug("control-received", msg=msg)
                await send_stream.send(msg)

    async def _message_consumer(self, receive_stream):
        attempts = 0

        while True:
            # Wait for a control message from the queue, but proceed anyway
            # with a rebalance check after a long sleep.
            async with anyio.move_on_after(self.processor.assignment_sleep):
                await receive_stream.receive()

            try:
                completed = await self.maybe_rebalance()
            except NoPartitionsAssigned:
                # A configuration error -- there are more group members than stream
                # partitions. Wait until one becomes available.
                logger.warning("no-partitions-assigned")
                attempts = 0
            except AcquirePartitionLockFailed:
                # Our declared partition assignment is out of date (e.g. a new executor
                # has been added since we read it) or the current owner has not released
                # it yet, so we cannot acquire the locks for our declared partitions.
                attempts += 1
                if attempts >= self.processor.assignment_attempts:
                    # Either our partition assignment is incorrect or another worker is
                    # failing to respond to control messages to release its partition
                    # locks. Give up, killing this process.
                    logger.critical("rebalance-failed")
                    raise RebalanceFailed
                else:
                    # It's likely that the current owner is still processing its backlog
                    # of events and will release it soon.
                    logger.warning("could-not-acquire")
            else:
                if completed:
                    logger.info("rebalance-completed")
                    attempts = 0
                else:
                    logger.debug("rebalance-check-passed")

    async def maybe_rebalance(self):
        await self.processor.reap()
        result = await self.stream.app.redis.get(self.processor.members_key)
        members = json.loads(result)

        # The only way we're not a declared member is if we were deemed dead because our
        # heartbeat expired. This should never happen.
        assert self.id in members

        assigned = set(self.partitions[i] for i in members[self.id]["partitions"])
        await self.set_assigned(assigned)

        acquiring = self.need_acquire
        releasing = self.need_release

        if acquiring or releasing:
            logger.warning(
                "rebalancing",
                assigned=[p.number for p in assigned],
                owned=[p.number for p in self.owned]
            )

        if releasing:
            logger.info("waiting-to-release", partitions=[p.number for p in releasing])
            async with self.run_locks(releasing):
                await self.release(releasing)

        if acquiring:
            logger.info("waiting-to-acquire", partitions=[p.number for p in acquiring])
            async with self.run_locks(acquiring):
                await self.acquire(acquiring)

        if not assigned:
            assert len(members) >= self.stream.partition_count
            raise NoPartitionsAssigned

        if acquiring or releasing:
            return True

    async def acquire(self, partitions):
        client = self.app.redis
        keys = [self.redis_lock_key(p.number) for p in partitions]
        px = self.lock_expiry * 1000

        async with await client.pipeline(transaction=True) as pipe:
            for key in keys:
                await pipe.set(key, self.id, nx=True, px=px)
            acquired = await pipe.execute()
            failed = False

        new = set()
        for p, success in zip(partitions, acquired):
            if success:
                p.reset()
                new.add(p)
            else:
                failed = True
        await self.set_owned(self.owned | new)

        if failed:
            logger.debug("failed-to-acquire", result=acquired)
            raise AcquirePartitionLockFailed
        logger.debug("acquired-partitions", partitions=[p.number for p in partitions])

    async def release(self, partitions, suppress_cancelled=False):
        client = self.app.redis
        fn = self.app.scripts["lock_release"]
        keys = [self.redis_lock_key(p.number) for p in partitions]

        async with await client.pipeline(transaction=True) as pipe:
            for key in keys:
                await fn.execute(client=pipe, keys=[key], args=[self.id])

            # Shield the execution from cancellation to ensure the locks are released.
            async with anyio.fail_after(4, shield=True):
                await pipe.execute()

        try:
            await self.set_owned(self.owned - partitions)
        except anyio.get_cancelled_exc_class():
            if not suppress_cancelled:
                raise
        finally:
            logger.debug("released-partitions", partitions=[p.number for p in partitions])

    async def extend(self):
        if self.owned:
            client = self.app.redis
            fn = self.app.scripts["lock_extend"]
            keys = [self.redis_lock_key(p.number) for p in self.owned]
            px = self.lock_expiry * 1000

            async with await client.pipeline(transaction=True) as pipe:
                for key in keys:
                    await fn.execute(client=pipe, keys=[key], args=[self.id, px])
                extended = await pipe.execute()

            if not all(extended):
                raise ExtendPartitionLockFailed
            logger.debug("extended-partitions", partitions=[p.number for p in self.owned])
