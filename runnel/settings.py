from datetime import tzinfo
from typing import Union

import pytz
from pydantic import BaseSettings, PyObject

from runnel.constants import ExceptionPolicy


class Settings(BaseSettings):
    """
    This class should not be used directly, but acts as a container for application
    settings, configured via environment variables (e.g. `RUNNEL_LOG_LEVEL=debug`) or as
    kwargs to the App object.

    Many of the settings represent defaults for processors or streams and can be
    overridden at object initialisation time.

    Parameters
    ----------
    redis_url : str
        The URL to pass to aredis.StrictRedis.from_url. Default: ``"127.0.0.1:6379"``.
    log_format : str
        Either ``"json"`` or ``"console"`` to specify the log output format.
    log_level : str
        The minimum log level to display: one of ``"debug"``, ``"info"``, ``"warning"``
        is recommended.
    autodiscover : str
        The pattern for :func:`pathlib.Path.glob` to find modules containing
        Runnel app-decorated functions (e.g. processors, tasks), which the worker must
        import on startup. Will be called relative to current working directory. For
        example, use ``'myproj/**/streams.py'`` to find all modules called 'streams'
        inside the 'myproj' folder. Default ``None``.
    timezone : tzinfo
        The timezone to use by default for ``app.crontab`` schedules. Default: ``pytz.UTC``.
    leadership_poll_interval : int (milliseconds)
        How long to sleep between worker leadership election attempts. Default: ``4000``
    testing : bool
        Whether we are currently running the test suite.
    default_serializer : Serializer
        An object implementing the Serialzer interface which controls how records
        are stored in the Redis streams. Default: ``JSONSerialzer`` unless ``orjson`` is
        installed (use the ``runnel[fast]`` bundle to install automatically), in which
        case ``FastJSONSerializer``.
    default_partition_count : int
        How many partitions to create. Default: ``16``.
    default_partition_size : int
        The max length of each partition. (Implemented approximately via Redis' MAXLEN
        option to XACK.) Represents the size of the buffer in case processors are
        offline or cannot keep up with the event rate. Default: ``50_000``.
    default_hasher: Callable[Any, int]
        A function used to hash a record's partition key to decide which partition to
        send it to. Defaults to md5 unless `xxhash` is installed (use the `runnel[fast]`
        bundle to install automataically)
    default_exception_policy : ExceptionPolicy
        How to handle exceptions raised in the user-provided processor coroutine.

        * ``HALT``: Raise the exception, halting execution of the affected partition.
        * ``QUARANTINE``: Mark the affected partition as poisoned, and continue with others.
        * ``IGNORE``: Suppress the exception and continue processing regardless.

        Default: ``HALT``.
    default_lock_expiry : int (seconds)
        The duration of the lock on stream partitions owned by executors of this
        processor. This controls the worst case lag a partition's events may
        experience since other executors will have to wait acquire the lock in case
        the owner has died. Default: ``120``.
    default_read_timeout : int (milliseconds)
        How long to stay blocked reading from Redis via XREADGROUP. Should be smaller
        than the ``grace_period`` given to processors. Default: ``2000``.
    default_prefetch_count : int
        The maximum number of events to read from Redis per partition owned by an
        executor. (If a single executor owns all 16 partitions in a stream and
        prefetch_count is 10, then 160 events may be read at once.) Purely an
        optimisation. Default: ``8``.
    default_assignment_attempts : int
        How many times to try to complete a rebalance operation (i.e. acquire our
        declared partitions) before giving up. Default: ``32``.
    default_assignment_sleep : float (seconds)
        How long to wait between attempts to complete a rebalance operation.
        Default: ``2``.
    default_grace_period : float (seconds)
        How long to wait for execution to complete gracefully before cancelling it.
        Default: ``8``.
    default_pool_size : int
        How many concurrent connections to make to Redis to read events. Default: ``16``.
    default_join_delay : int (seconds)
        How long to wait after joining before attempting to acquire partitions.
        Intended to mitigate a thundering herd problem of multiple workers joining
        simultaneously and needing to rebalance multiple times. Default: ``2``.
    """
    class Config:
        env_prefix = "RUNNEL_"
        case_insensitive = True

    redis_url: str = "redis://127.0.0.1:6379"
    log_format: str = "console"
    log_level: str = "info"
    autodiscover: str = None
    timezone: tzinfo = pytz.UTC
    leadership_poll_interval: int = 4000
    testing: bool = False

    # Stream defaults
    default_partition_count: int = 16
    default_partition_size = 50_000
    default_serializer: Union[PyObject, str] = "runnel.serialization.default"
    default_hasher: Union[PyObject, str] = "runnel.hashing.default"

    # Processor defaults
    default_exception_policy: ExceptionPolicy = ExceptionPolicy.HALT
    default_lock_expiry: int = 60 * 2
    default_read_timeout: int = 2000
    default_prefetch_count: int = 8
    default_assignment_attempts: int = 32
    default_assignment_sleep: float = 2
    default_grace_period: float = 8
    default_pool_size: int = 16
    default_join_delay: int = 2
