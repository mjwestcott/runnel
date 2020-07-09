import structlog

from runnel.interfaces import Middleware
from runnel.types import Event

logger = structlog.get_logger(__name__)


class Ack(Middleware):
    async def handler(self, parent, events, **kwargs):
        async for x in parent:
            assert isinstance(x, (Event, list))
            try:
                yield x
            except GeneratorExit:
                logger.warning("marking-failed", x=x)
                # Mark the offending event (or events) against the root generator so
                # that we can clean up according to the exception policy.
                if isinstance(x, Event):
                    events.failed.add(x)
                else:
                    events.failed.update(x)
                raise
            else:
                if isinstance(x, Event):
                    await events.stream.ack(x)
                else:
                    await events.stream.ack(*x)
