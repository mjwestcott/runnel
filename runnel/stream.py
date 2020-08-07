from dataclasses import dataclass, replace
from functools import lru_cache
from typing import TYPE_CHECKING, Any, Callable, Iterable, Type, Union

import structlog

from runnel.exceptions import Misconfigured
from runnel.interfaces import Serializer
from runnel.record import Record

if TYPE_CHECKING:
    from runnel.app import App

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class Stream:
    """
    A set of partitioned Redis streams, together representing a single logical event
    stream.

    Not intended to be used directly. Use :attr:`runnel.App.stream` instead.
    """
    app: "App"
    name: str
    record: Type[Record]
    partition_by: Union[str, Callable]
    serializer: Serializer  # Not applicable for records with primitive=True.
    hasher: Callable[[Any], int]
    partition_count: int
    partition_size: int

    def __post_init__(self):
        if self.record._primitive and self.serializer:
            raise Misconfigured("Cannot serialize primitive records")

        by = self.partition_by
        if isinstance(by, str) and not by in self.record.__fields__:
            raise Misconfigured("Stream.partition_by must specify a record field")

    def __hash__(self):
        return hash(self.id)

    def clone(self, **kwargs):
        return replace(self, **kwargs)

    @property
    def id(self):
        return f"{self.app.name}.{self.name}"

    @lru_cache
    def partition_key(self, i):
        return f"__strm:{self.id}.{i}"

    @lru_cache
    def all_partition_keys(self):
        return [self.partition_key(i) for i in range(0, self.partition_count)]

    def route(self, key):
        return self.partition_key(self.hash(key))

    def hash(self, key):
        return self.hasher(key) % self.partition_count

    async def send(self, *records: Iterable[Record], stream_ids=None):
        """
        Send records to partitions of the stream, according to their partition keys.

        Parameters
        ----------
        records : Iterable[Record]
            The records to send.
        stream_ids : Optional[Iterable[str]]
            A list of stream_ids corresponding to the records. Must be the same length
            as records. If ``None``, then ``"*"`` will be used for all records. See
            `<https://redis.io/commands/xadd>`_ for more details.
        """
        if not stream_ids:
            stream_ids = ["*" for _ in range(len(records))]
        assert len(stream_ids) == len(records)

        async with await self.app.redis.pipeline() as pipe:
            for record, stream_id in zip(records, stream_ids):
                await pipe.xadd(
                    name=self.route(self._compute_key(record)),
                    entry=self.serialize(record),
                    max_len=self.partition_size,
                    approximate=True,
                    stream_id=stream_id
                )
            await pipe.execute()

    async def read(self, group, consumer, prefetch, timeout, **keys):
        return await self.app.redis.xreadgroup(  # yapf: disable
            group=group,
            consumer_id=consumer,
            count=prefetch,
            block=timeout,
            **keys,
        )

    async def ack(self, *events):
        if len(events) == 1:
            e = events[0]
            await self.app.redis.xack(e.partition.key, e.group, e.xid)
        else:
            keys = {}

            # XACK supports multiple ids in one command, but only per
            # key and consumer group, so we must preprocess the events.
            for e in events:
                if e.partition.key not in keys:
                    keys[e.partition.key] = {}
                if e.group not in keys[e.partition.key]:
                    keys[e.partition.key] = {e.group: []}

                keys[e.partition.key][e.group].append(e.xid)

            async with await self.app.redis.pipeline() as pipe:
                for key, groups in keys.items():
                    for group, xids in groups.items():
                        await pipe.execute_command(*["XACK", key, group, *xids])
                await pipe.execute()
        logger.debug("acked", events=[e.data for e in events])

    def _compute_key(self, record):
        if isinstance(self.partition_by, str):
            return getattr(record, self.partition_by)
        elif isinstance(self.partition_by, Callable):
            return self.partition_by(record)

    def serialize(self, record):
        if self.record._primitive:
            return {k.encode("utf-8"): v for k, v in record.dict().items()}

        value = self.serializer.dumps(record.dict())
        if self.serializer.compressor:
            value = self.serializer.compressor.compress(value)
        return {b"data": value}

    def deserialize(self, value):
        if self.record._primitive:
            value = {k.decode("utf-8"): v for k, v in value.items()}
        else:
            value = value[b"data"]
            if self.serializer and self.serializer.compressor:
                value = self.serializer.compressor.decompress(value)
            value = self.serializer.loads(value)

        return self.record(**value)
