from typing import Callable, Coroutine, Dict, Set

import anyio
import structlog
from aredis import StrictRedis

from runnel.exceptions import Misconfigured
from runnel.logging import init_logging
from runnel.processor import Processor
from runnel.settings import Settings
from runnel.stream import Stream
from runnel.utils import seconds_until
from runnel.worker import Worker

logger = structlog.get_logger(__name__)


class App:
    """
    This is the main abstraction provided by Runnel. Use the :meth:`~.stream` and
    :meth:`~.processor` methods to define partitioned event streams and processors
    respectively. Apps will be run by workers via the CLI.

    Parameters
    ----------
    name : str
        An app identifier. Will be used as a component of the Redis keys for the
        under-the-hood data structures.
    kwargs : Dict
        Any of the settings found in :mod:`runnel.settings` to override any options
        provided by environment variables.

    Examples
    --------
    >>> from runnel import App, Record
    ...
    >>> app = App(
    ...     name="example",
    ...     log_level="info",
    ...     redis_url="127.0.0.1:6379",
    ... )

    Specify your event types using the Record class:

    >>> class Order(Record):
    ...     order_id: int
    ...     created_at: datetime
    ...     amount: int
    ...     item_ids: List[int]

    Streams are configured to be partitioned by a chosen key.

    >>> orders = app.stream("orders", record=Order, partition_by="order_id")

    Processor functions iterate over the event stream and can rely on receiving events
    in the order they were created per key.

    >>> @app.processor(orders)
    ... async def printer(events):
    ...     async for order in events.records():
    ...         print(order.amount)

    Under the hood, Runnel will take care of partitioning the stream to enable scalable
    distributed processing. We also take care of concurrently running the async processor
    functions -- one for every partition in your stream. This processing may be
    distributed across many workers on different machines and Runnel will coordinate
    ownership of partitions dynamically as workers join or leave.
    """
    def __init__(self, name: str, **kwargs):
        self.name: str = name
        self.settings: Settings = Settings(**kwargs)
        self.redis = StrictRedis.from_url(self.settings.redis_url)
        self.workers: Set[Worker] = set()
        self.tasks: Set[Coroutine] = set()
        self.processors: Dict[str, Coroutine] = {}
        self.scripts: Dict[str, Callable] = {}

        init_logging(
            level=self.settings.log_level,
            format=self.settings.log_format,
        )

    def stream(
        self,
        name,
        record,
        partition_by,
        serializer=None,
        partition_count=None,
        partition_size=None,
        hasher=None,
    ):
        """
        A set of partitioned Redis streams, containing events as structured Record types.

        Kwargs, if provided, will override the default settings configured on the App
        instance or via environment variables (see :mod:`runnel.settings`) for this
        stream.

        Parameters
        ----------
        name : str
            An stream identifier. Will be used as a component of the Redis keys for the
            under-the-hood data structures.
        record: Type[Record]
            A class that inherits from Record, which specifies the structure of the event
            data this stream expects. See :class:`runnel.Record`.
        partition_by : Union[str, Callable[Record, Any]]
            A str representing an attribute of the Record type (or a callable to compute
            a value) which should be used to partition events. For example, if your events
            concern user activity and you want to process events in-order per user, you
            might choose the "user_id" attribute to partition by.
        serializer : Serializer
            An object implementing the :class:`runnel.interfaces.Serializer` interface
            which controls how records are stored in the Redis streams.
        partition_count : int
            How many partitions to create.
        partition_size : int
            The max length of each partition. (Implemented approximately via Redis' MAXLEN
            option to XACK.) Represents the size of the buffer in case processors are
            offline or cannot keep up with the event rate.
        hasher: Callable[Any, int]
            A function used to hash the partition key to decide to which partition to
            send a record.

        Examples
        --------
        >>> from runnel import App, Record, JSONSerializer
        ...
        >>> app = App(name="example")
        ...
        >>> class Order(Record):
        ...     order_id: int
        ...     amount: int

        Streams are configured to be partitioned by a chosen key.

        >>> orders = app.stream(
        ...     name="orders",
        ...     record=Order,
        ...     partition_by="order_id",
        ...     partition_count=16,
        ...     serializer=JSONSerializer(),
        ... )
        """
        if serializer is None and not record._primitive:
            serializer = self.settings.default_serializer

        return Stream(
            app=self,
            name=name,
            record=record,
            partition_by=partition_by,
            serializer=serializer,
            partition_count=partition_count or self.settings.default_partition_count,
            partition_size=partition_size or self.settings.default_partition_size,
            hasher=hasher or self.settings.default_hasher,
        )

    def processor(
        self,
        stream,
        *,
        name=None,
        exception_policy=None,
        middleware=None,
        lock_expiry=None,
        read_timeout=None,
        prefetch_count=None,
        assignment_attempts=None,
        assignment_sleep=None,
        grace_period=None,
        pool_size=None,
        join_delay=None
    ):
        """
        A wrapper around an async Python function which iterates over a continuous event
        stream.

        Kwargs, if provided, will override the default settings configured on the App
        instance or via environment variables (see :mod:`runnel.settings`) for this
        processor.

        Notes
        -----
        Events are acknowledged at the end of every processing loop. This means that if
        your processor crashed before completion, that section of work will be repeated
        when the processor is restarted. Therefore Runnel provides 'at least once'
        semantics.

        Parameters
        ----------
        stream : runnel.App.stream
            The stream this processor will iterate over.
        name : str
            Used in the Redis keys relating to this processor. Must be unique together
            with the App and Stream. Default: your function's ``__name__``.
        exception_policy : ExceptionPolicy
            How to handle exceptions raised in the user-provided processor coroutine.

            * ``HALT``: Raise the exception, halting execution of the affected partition.
            * ``QUARANTINE``: Mark the affected partition as poisoned, and continue with others.
            * ``IGNORE``: Suppress the exception and continue processing regardless.

            Default: ``HALT``.
        middleware : List[Middleware]
            A list of Middleware objects for managaing the data pipeline. Can be used to
            implement custom exception handling (e.g. dead letter queues).
        lock_expiry : int (seconds)
            The duration of the lock on stream partitions owned by executors of this
            processor. This controls the worst case lag a partition's events may
            experience since other executors will have to wait acquire the lock in case
            the owner has died.
        read_timeout : int (milliseconds)
            How long to stay blocked reading from Redis via XREADGROUP. Nothing depends
            on this.
        prefetch_count : int
            The maximum number of events to read from Redis per partition owned by an
            executor. (If a single executor owns all 16 partitions in a stream and
            prefetch_count is 10, then 160 events may be read at once.) Purely an
            optimisation.
        assignment_attempts : int
            How many times to try to complete a rebalance operation (i.e. acquire our
            declared partitions) before giving up.
        assignment_sleep : float (seconds)
            How long to wait between attempts to complete a rebalance operation.
        grace_period : float (seconds)
            How long to wait for execution to complete gracefully before cancelling it.
        pool_size : int
            How many concurrent connections to make to Redis to read events.
        join_delay : int (seconds)
            How long to wait after joining before attempting to acquire partitions.
            Intended to mitigate a thundering herd problem of multiple workers joining
            simultaneously and needing to rebalance multiple times.

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
        if not isinstance(stream, Stream):
            raise Misconfigured("You must pass a stream to the app.processor decorator")

        kwargs = {
            "exception_policy": exception_policy or self.settings.default_exception_policy,
            "middleware": middleware or [],
            "lock_expiry": lock_expiry or self.settings.default_lock_expiry,
            "read_timeout": read_timeout or self.settings.default_read_timeout,
            "prefetch_count": prefetch_count or self.settings.default_prefetch_count,
            "assignment_attempts": assignment_attempts or self.settings.default_assignment_attempts,
            "assignment_sleep": assignment_sleep or self.settings.default_assignment_sleep,
            "grace_period": grace_period or self.settings.default_grace_period,
            "pool_size": pool_size or self.settings.default_pool_size,
            "join_delay": join_delay or self.settings.default_join_delay,
        }

        def decorator(f):
            nonlocal name
            proc = Processor(stream=stream, f=f, name=name or f.__name__, **kwargs)
            logger.debug("found-processor", name=proc.name)

            if proc.id in self.processors:
                raise Misconfigured("Processor name must be unique within an App and Stream")

            self.processors[proc.id] = proc
            return proc

        return decorator

    def _task(self, func):
        def decorator(f):
            self.tasks.add(f)
            return func

        return decorator(func)

    def task(self, func=None, *, on_leader=False):
        """
        Define an async function to run at worker startup.

        Parameters
        ----------
        on_leader : bool
            Whether to run the function only on one worker: the elected leader.

        Examples
        --------
        >>> @app.task
        >>> async def on_startup():
        ...     print("starting")

        If you want the task to run on only one worker:

        >>> @app.task(on_leader=True)
        >>> async def on_startup():
        ...    print(f"running once")
        """
        def decorator(f):
            async def wrapper(worker):
                if not on_leader or worker.is_leader:
                    logger.info("running-task", name=f.__name__)
                    await f()

            logger.debug("found-task", name=f.__name__)
            return self._task(wrapper)

        return decorator(func) if func is not None else decorator

    def timer(self, *, interval: int, on_leader=False):
        """
        Define an async function to be run at periodic intervals.

        Parameters
        -----------
        interval : float (seconds)
            How often the function executes in seconds.
        on_leader : bool
            Whether to run the function only on one worker: the elected leader.

        Examples
        --------
        >>> @app.timer(interval=10)
        >>> async def every_10_seconds():
        ...     print("10 seconds passed")

        If you want the task to run on only one worker:

        >>> app.timer(interval=5, on_leader=True)
        >>> async def every_5_seconds():
        ...     print("5 seconds passed on the leader")
        """
        def decorator(f):
            async def timer_spawner(worker) -> None:
                async with anyio.create_task_group() as tg:
                    logger.debug("background-timer-task", name=f.__name__)
                    while True:
                        await anyio.sleep(interval)
                        if not on_leader or worker.is_leader:
                            logger.debug("spawning-timer-task", name=f.__name__)
                            await tg.spawn(f)

            logger.debug("found-timer", name=f.__name__)
            return self._task(timer_spawner)

        return decorator

    def crontab(self, spec: str, *, timezone=None, on_leader=False):
        """
        Define an async function to be run at the fixed times, defined by the Cron
        format (see `<https://crontab.guru/>`_ for examples).

        Parameters
        ----------
        spec : str
            The Cron spec defining fixed times to run the decorated function.
        timezone : tzinfo
            The timezone to be taken into account for the Cron jobs. If not set value
            from :attr:`runnel.settings.Settings.timezone` will be taken.
        on_leader : bool
            Whether to run the function only on one worker: the elected leader.

        Examples
        --------
        >>> app.crontab("45 17 * * *")
        >>> async def every_5_45_pm():
        ...     print("It is 5:45pm UTC")

        If you want the task to run on only one worker:

        >>> app.crontab("45 17 * * *", on_leader=True)
        >>> async def every_5_45_pm():
        ...     print("It is 5:45pm UTC on the leader")

        With a timezone specification:

        >>> @app.crontab("45 17 * * *", timezone=pytz.timezone('GMT'))
        >>> async def every_5_45_pm():
        ...     print("It is 5:45pm in London")
        """
        def decorator(f):
            async def cron_spawner(worker) -> None:
                _tz = self.settings.timezone if timezone is None else timezone
                async with anyio.create_task_group() as tg:
                    logger.debug("background-cron-task", name=f.__name__)
                    while True:
                        await anyio.sleep(seconds_until(spec, _tz))
                        if not on_leader or worker.is_leader:
                            logger.debug("spawning-cron-task", name=f.__name__)
                            await tg.spawn(f)

            logger.debug("found-cron", name=f.__name__)
            return self._task(cron_spawner)

        return decorator
