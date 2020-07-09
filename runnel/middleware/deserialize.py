import structlog

from runnel.interfaces import Middleware
from runnel.types import Event

logger = structlog.get_logger(__name__)


class Deserialize(Middleware):
    async def handler(self, parent, events, **kwargs):
        async for x in parent:
            assert isinstance(x, (Event, list))

            if isinstance(x, Event):
                yield events.stream.deserialize(x.data)
            else:
                yield [events.stream.deserialize(event.data) for event in x]
