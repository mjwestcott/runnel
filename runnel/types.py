import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Dict

import anyio
import structlog

if TYPE_CHECKING:
    from runnel.stream import Stream
    from runnel.runner import Runner

logger = structlog.get_logger(__name__)


@dataclass
class Partition:
    """
    The internal representation of a partition of the stream.

    Attributes
    ----------
    number : int
        Which numerical partition this is.
    key : str
        The Redis key under which the stream data structure is stored.
    """
    stream: "Stream"
    number: int
    pointer: bytes = b"0-0"
    lock: anyio.abc.Lock = field(default_factory=anyio.create_lock)

    def __hash__(self):
        return object.__hash__(self)

    def __repr__(self):
        return f"<Partition stream={self.stream.name} i={self.number} pointer={self.pointer}>"

    @property
    def key(self):
        return self.stream.partition_key(self.number)

    def reset(self):
        # A new owner for this partition, reset the pointer so that Redis will return
        # values from the pending entries list if any exist.
        self.pointer = b"0-0"


@dataclass
class Event:
    """
    The internal representation of an event in a stream. Will ordinarily by deserialized
    into a Record type before it is acted upon: e.g. via ``async for record in
    events.records():``. This low-level representation is also available if necessary.

    Attributes
    ----------
    partition: Partition
        The partition this event came from.
    xid: bytes
        The Redis stream ID.
    data : Dict[bytes, bytes]
        The keys and values retrieved from the Redis stream.

    Examples
    --------
    >>> @app.processor(order)
    ... async def myproc(events):
    ...     async for event in events:
    ...         print(event.xid)
    """
    runner: "Runner"
    partition: "Partition"
    group: bytes
    xid: bytes
    data: Dict[bytes, bytes]
    recovering: bool

    def __hash__(self):
        return hash((self.partition, self.xid))

    def __repr__(self):
        if os.environ["RUNNEL_TESTING"] == "1":
            return f"<Event data={self.data}>"
        return f"<Event stream={self.partition.stream.name} partition={self.partition.number} xid={self.xid}>"
