from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from functools import lru_cache
from typing import TYPE_CHECKING, Dict, Set

import anyio
import structlog

from runnel.concurrency import WatermarkQueue, race
from runnel.constants import ExceptionPolicy
from runnel.context import partition_id
from runnel.events import Events
from runnel.types import Event, Partition

if TYPE_CHECKING:
    from runnel.executor import Executor

logger = structlog.get_logger(__name__)


@dataclass
class Runner:
    """
    The Runner is responsible for concurrently running a user-provided processor
    function for every partition owned by the Executor. It will pass the function
    an events generator which must be fed events from a queue.
    """
    executor: "Executor"
    partitions: Dict[Partition, WatermarkQueue] = field(default_factory=dict)
    new_joiner: anyio.abc.Event = field(default_factory=anyio.create_event)
    new_leaver: anyio.abc.Event = field(default_factory=anyio.create_event)
    fetch_completed: anyio.abc.Event = field(default_factory=anyio.create_event)
    fetching: Set[Partition] = field(default_factory=set)
    pool: anyio.abc.Semaphore = None

    def __post_init__(self):
        self.pool = anyio.create_semaphore(self.processor.pool_size)

    @property
    def processor(self):
        return self.executor.processor

    @property
    def stream(self):
        return self.executor.stream

    @property
    def prefetch_count(self):
        return self.processor.prefetch_count

    def need_change(self) -> bool:
        return set(self.partitions) < self.executor.safe_partitions

    def with_space(self) -> Set[Partition]:
        return {p for p, q in self.partitions.items() if q.qsize() < self.prefetch_count}

    def can_fetch(self) -> Set[Partition]:
        return set(self.partitions) - self.fetching

    def should_fetch(self) -> Set[Partition]:
        return self.with_space() - self.fetching

    async def wait_queues_ready(self, queues):
        await race(*[q.wait_for_watermark() for q in queues])

    async def wait_until_should_fetch(self):
        coros = [self.new_joiner.wait(), self.fetch_completed.wait()]
        queues = [self.partitions[p] for p in self.can_fetch()]
        if queues:
            coros.append(self.wait_queues_ready(queues))
        await race(*coros)

    @asynccontextmanager
    async def is_running(self, partition: "Partition"):
        async with partition.lock:
            await self.new_joiner.set()
            self.new_joiner = anyio.create_event()
            try:
                yield
            finally:
                logger.debug("consumer-cleanup")
                # Remove the partition from the set managed by this Runner. This will
                # cause any pending fetches to abort when they complete.
                del self.partitions[partition]

                # Wait until any pending fetches for the partition complete. Otherwise,
                # there's a race condition between the current fetcher and the one that
                # will own the partition next. This fetcher will read, but not ack, and
                # any events will stay in the PEL. Since we read as the same Redis
                # group/consumer, depending on its startup time the new owner might miss
                # the events read by this fetcher.
                while partition in self.fetching:
                    await self.fetch_completed.wait()

                # Reset the partition's pointer so that the next task to take ownership
                # starts by reading the pending entries list. This is necessary because
                # we may have read, but not processed, some events.
                partition.reset()

                # Notify any waiting tasks that we are about to exit and relinquish our
                # run lock.
                await self.new_leaver.set()
                self.new_leaver = anyio.create_event()
                logger.debug("consumer-exit")

    async def run(self):
        try:
            logger.debug("runner-starting")
            async with anyio.create_task_group() as tg:
                # A background task that fetches events from Redis
                # and puts them in a queue per partition.
                await tg.spawn(self.fetcher)

                while True:
                    # Ensure that all partitions owned by our Executor have running consumer
                    # tasks. They are responsible for running the user-provided processor
                    # function and passing it an events generator.
                    logger.debug("runner-loop", partitions=self.partitions)
                    if not self.need_change():
                        logger.debug("runner-waiting")
                        await race(self.executor.wait_for(self.need_change), self.new_leaver.wait())

                    for p in self.executor.safe_partitions:
                        if p not in self.partitions:
                            self.partitions[p] = WatermarkQueue(self.prefetch_count)
                            logger.debug("spawning-consumer", partition=p)
                            await tg.spawn(self.consumer, p)
        finally:
            logger.debug("runner-exit")

    async def consumer(self, partition: "Partition"):
        # Run the processor function over an events generator for a single partition.
        partition_id.set(partition.number)

        async with self.is_running(partition):
            try:
                logger.debug("starting-consumer")
                events = Events(runner=self, partition=partition)

                async with anyio.create_task_group() as tg:
                    await tg.spawn(self.processor.f, events)
                    await self.executor.wait_for(lambda: partition in self.executor.need_release)

                    # The event generator will close gracefully now on the next
                    # iteration through its read loop when it discovers that its
                    # partition needs release. This graceful exit is important, because
                    # it allows the pipeline to ack all the events it has seen, which
                    # prevents duplicate processing once rebalancing is complete.
                    async with anyio.move_on_after(self.processor.grace_period) as scope:
                        logger.debug("consumer-grace-period")
                        await events.finalized.wait()

                    if scope.cancel_called:
                        # The grace period was exceeded, forcefully cancel the
                        # processor. Duplicate processing of unacked events is likely.
                        logger.critical("consumer-grace-period-exceeded")
                        await tg.cancel_scope.cancel()
            except Exception:
                logger.exception("consumer-failed")
                await events.aclose()
                assert events.finalized and events.failed

                policy = self.processor.exception_policy
                if policy == ExceptionPolicy.HALT:
                    # Propagate the exception, killing this executor and any others who
                    # end up taking ownership of this partition. The nuclear option.
                    raise
                elif policy == ExceptionPolicy.QUARANTINE:
                    # It is assumed that the exception is unrecoverable (e.g. a
                    # deserialization error occurred or user-processor code failed).
                    # Mark the offending partition as poisoned and do not attempt to
                    # read from it again. Manual intervention is required to make
                    # progress on that partition -- at a minimum the bad event must be
                    # deleted.
                    self.executor.poisoned.update({e.partition for e in events.failed})
                elif policy == ExceptionPolicy.IGNORE:
                    # Simply ack the failed events. They will not be processed again.
                    # Can be used with dead-letter-queue middleware to implement an
                    # effective strategy for always making forward progress.
                    await self.executor.stream.ack(*events.failed)
            finally:
                await events.aclose()

    async def fetcher(self):
        # 1) We want to use as few connections as possible (i.e. avoid n connections for
        # n partitions if every consumer fetched its own events).
        # 2) We want to allow slow partitions to fall behind, not impacting others, and
        # not buffering too many events in memory.
        # 3) We want to use the blocking XREADGROUP command (rather than
        # constant polling) for efficiency.
        # These demands explain the fetching scheme implemented below, which spawns
        # concurrent fetch tasks, limited by a semaphore, for partitions with queue
        # space.
        async with anyio.create_task_group() as tg:
            while True:
                partitions = self.should_fetch()
                if partitions:
                    self.fetching.update(partitions)
                    await tg.spawn(self.fetch, partitions)
                else:
                    logger.debug("waiting-until-should-fetch")
                    await self.wait_until_should_fetch()

    async def fetch(self, partitions):
        try:
            async with self.pool:
                await self._fetch(partitions)
        finally:
            self.fetching.difference_update(partitions)
            await self.fetch_completed.set()
            self.fetch_completed = anyio.create_event()

    async def _fetch(self, partitions):
        logger.debug("fetching", partitions=partitions)

        results = await self.executor.stream.read(  # yapf: disable
            group=self.executor.group,
            consumer=self.executor.consumer,
            prefetch=self.executor.processor.prefetch_count,
            timeout=self.executor.processor.read_timeout,
            **{p.key: p.pointer for p in partitions},
        )

        for key, values in results.items():
            partition = self.key_to_partition(key)

            try:
                queue = self.partitions[partition]
            except KeyError:
                # A partition has left since beginning the fetch. (Its consumer could
                # have failed and exited, or it could have been reassigned in a
                # rebalance.)
                logger.debug("fetched-partition-not-owned", partition=partition)
                continue

            for xid, data in values:
                logger.debug("putting", partition=partition.number, xid=xid, data=data)
                await queue.put(
                    Event(
                        runner=self,
                        partition=partition,
                        group=self.executor.group,
                        xid=xid,
                        data=data,
                        recovering=partition.pointer != b">",
                    )
                )

            if partition.pointer == b">":
                continue
            elif values:
                # We are reading the PEL, update the pointer to last seen.
                partition.pointer = xid
            else:
                # We have finished reading from the PEL, recovery over.
                partition.pointer = b">"

    def key_to_partition(self, key):
        return self.executor.partitions[self.key_to_int(key)]

    @staticmethod
    @lru_cache(maxsize=2**12)
    def key_to_int(key):
        return int(key.split(b".")[-1])
