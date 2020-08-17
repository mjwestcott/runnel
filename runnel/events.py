from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, field
from typing import (
    TYPE_CHECKING,
    AsyncIterator,
    List,
    Optional,
    Set,
    Tuple,
    Union,
)

import anyio
import structlog
from aiostream.aiter_utils import aitercontext

from runnel.exceptions import Misconfigured
from runnel.middleware import Ack, Deserialize, Take

if TYPE_CHECKING:
    from runnel.runner import Runner
    from runnel.types import Partition, Event

logger = structlog.get_logger(__name__)


@dataclass
class Events:
    """
    An async generator which yields Events (or batches of them). This is the object
    passed to user-defined processor functions.

    Examples
    --------
    >>> from runnel import App, Record
    ...
    >>> app = App(name="example")
    ...
    >>> class Order(Record):
    ...     order_id: int
    ...     amount: int
    ...
    >>> orders = app.stream(name="orders", record=Order, partition_by="order_id")
    ...
    >>> @app.processor(orders)
    ... async def printer(events):
    ...     async for order in events.records():
    ...         print(order.amount)
    """
    runner: "Runner"
    partition: "Partition"
    want: str = "events"
    batch_args: Optional[Tuple] = None
    failed: Set["Event"] = field(default_factory=set)
    finalized: anyio.abc.Event = field(default_factory=anyio.create_event)
    agen: AsyncIterator[Union["Event", List["Event"]]] = None

    @property
    def executor(self):
        return self.runner.executor

    @property
    def stream(self):
        return self.executor.stream

    def __call__(self):
        return self

    def take(self, n, within):
        """
        Configure the events generator to yield batches of `n` events (unless `within`
        seconds pass before `n` are ready, in which case yield all pending events).

        Parameters
        ----------
        n : int
            The desired batch size.
        within : int (seconds)
            The duration to wait for the batch size to be reached before yielding.

        Examples
        --------
        >>> @app.processor(orders)
        ... async def printer(events):
        ...     async for orders in events.take(10, within=1).records():
        ...         # Handle orders as an atomic batch!
        ...         assert 1 <= len(orders) <= 10
        ...         print(orders)

        Notes
        -----
        This method is provided for efficiency. It is intended to be used where batch
        processing of events greatly increases your processing speed. For example, if
        you are loading records into a database, you may want to use its bulk import API
        to ingest a batch of records at a time.

        Warning
        -------
        Runnel acks events after every iteration through the event generator loop. When
        using `take`, this means the entire batch will be acked at once. As a result,
        you must process the batch as a single unit atomically. If you iterate over the
        events in a batch one-at-a-time and you fail half-way through, then the entire
        batch will be considered failed (and handled according to your
        :attr:`runnel.constants.ExceptionPolicy`). This will lead to duplicate
        processing if the batch is retried, or dropped events if the batch is ignored.
        """
        if within > self.executor.processor.grace_period:
            raise Misconfigured("Cannot wait longer than grace_period for a batch")

        self.batch_args = (n, within)
        return self

    def records(self):
        """
        Configure the events generator to deserialize events into Record objects.

        Examples
        --------
        >>> from runnel import Record
        ...
        >>> @app.processor(orders)
        ... async def printer(events):
        ...     async for order in events.records():
        ...         assert isinstance(event, Record)
        ...         print(order.amount)

        If this method is omitted, you will iterate over the low-level :class:`runnel.Event`
        objects, which gives you access to the raw data as ``Dict[bytes, bytes]``.

        >>> from runnel import Event
        ...
        >>> @app.processor(orders)
        ... async def printer(events):
        ...     async for event in events:
        ...         assert isinstance(event, Event)
        ...         print(event.data)
        """
        self.want = "records"
        return self

    def __aiter__(self):
        self.agen = self.iter()
        return self.agen

    async def aclose(self):
        assert self.agen, "Cannot close an event generator that is not running"
        await self.agen.aclose()

    async def iter(self):
        async with self.running():
            # Common kwargs to all middleware handlers.
            kwargs = {"events": self}

            async with AsyncExitStack() as stack:
                enter = stack.enter_async_context
                agen = await enter(aitercontext(self.root()))

                # Construct the middleware pipeline.
                if self.batch_args:
                    agen = await enter(aitercontext(Take(*self.batch_args).handler(agen, **kwargs)))

                # User-provided middleware, which must handle and yield either single
                # events or a batch.
                for m in self.executor.processor.middleware:
                    agen = await enter(aitercontext(m.handler(agen, **kwargs)))

                # Acknowledgement handling.
                agen = await enter(aitercontext(Ack().handler(agen, **kwargs)))

                # Automatic deserialisation.
                if self.want == "records":
                    agen = await enter(aitercontext(Deserialize().handler(agen, **kwargs)))

                # It begins.
                async for x in agen:
                    yield x

    async def root(self):
        queue = self.runner.partitions[self.partition]
        timeout = max(0.05, min(1, self.executor.processor.grace_period / 4))

        while self.partition in self.executor.safe_partitions:
            async with anyio.move_on_after(timeout) as scope:
                event = await queue.get()

            if not scope.cancel_called:
                yield event

    @asynccontextmanager
    async def running(self):
        logger.debug("events-started")
        assert not self.finalized.is_set()
        try:
            yield
        finally:
            await self.finalized.set()
            logger.debug("events-finally-ended")
