# yapf: disable
from datetime import datetime
from typing import Iterable

import structlog

from runnel.interfaces import Middleware
from runnel.record import Record
from runnel.types import Event

logger = structlog.get_logger(__name__)


# An example record to demonstrate forwarding of failed events to a dead letter queue.
# Stores the raw bytes since deserialization may have been responsible for the failure.
class Dead(Record, primitive=True):
    failed_at: str
    partition: str
    xid: str
    data: bytes

    @classmethod
    def from_event(cls, event: Event):
        return cls(
            failed_at=datetime.utcnow().isoformat(),
            partition=event.partition.key,
            xid=event.xid,
            data=event.data[b"data"],
        )


class DeadLetterMiddleware(Middleware):
    def __init__(self, source):
        self.source = source
        name = f"dead.{source.name}"

        if source.record._primitive:
            # Re-use the source record type as the dead record type so we don't
            # have to perform any serialization/deserialization.
            self.sink = source.clone(name=name, partition_count=1)
        else:
            # Use the example Dead type.
            self.sink = source.app.stream(
                name,
                record=Dead,
                partition_by="partition",
                partition_count=1,
            )

    async def handler(self, parent, **kwargs):
        async for x in parent:
            assert isinstance(x, (Event, list))
            try:
                yield x
            except GeneratorExit:
                try:
                    logger.warning("dead-letter-handling", x=x)
                    if isinstance(x, Event):
                        await self._send(x)
                    else:
                        await self._send(*x)
                except:
                    logger.exception("dead-letter-failed")
                raise

    async def _send(self, *events: Iterable[Event]):
        if self.source.record._primitive:
            # Convert the event back into the source record type.
            convert = lambda e: self.sink.record(**{k.decode("utf-8"): v for k, v in e.data.items()})
        else:
            convert = lambda e: Dead.from_event(e)

        # Forward to the sink stream.
        await self.sink.send(*[convert(e) for e in events])
