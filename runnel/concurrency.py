import math
from contextlib import asynccontextmanager

import anyio
import structlog

logger = structlog.get_logger(__name__)


async def race(*coros):
    """
    Run multiple coroutines and return the result of the first to finish, cancelling the
    rest.
    """
    if not coros:
        raise ValueError("race expects at least one argument")

    send_stream, receive_stream = anyio.create_memory_object_stream()

    async def f(coro):
        await send_stream.send(await coro)

    async with anyio.create_task_group() as tg:
        for coro in coros:
            await tg.spawn(f, coro)

        result = await receive_stream.receive()
        await tg.cancel_scope.cancel()

    return result


@asynccontextmanager
async def create_daemon_task_group():
    async with anyio.create_task_group() as tg:
        try:
            yield tg
        finally:
            await tg.cancel_scope.cancel()


class WatermarkQueue:
    """
    A queue that enables waiting until it has reached above or below a certain size.
    """
    def __init__(self, watermark: int, direction="lt"):
        self.watermark = watermark
        self.direction = direction
        self._event = anyio.create_event()

        s, r = anyio.create_memory_object_stream(max_buffer_size=math.inf)
        self._send_stream, self._receive_stream = s, r

    def qsize(self):
        # XXX: AnyIO doesn't provide an API for getting buffer statistics, so we're
        # using a private attribute.
        return len(self._receive_stream._state.buffer)

    async def put(self, item):
        await self._send_stream.send(item)
        if self.direction == "gt":
            if self.qsize() > self.watermark:
                await self._event.set()
                self._event = anyio.create_event()

    async def get(self):
        item = await self._receive_stream.receive()
        if self.direction == "lt":
            if self.qsize() < self.watermark:
                await self._event.set()
                self._event = anyio.create_event()
        return item

    async def wait_for_watermark(self):
        lt = self.direction == "lt" and self.qsize() >= self.watermark
        gt = self.direction == "gt" and self.qsize() <= self.watermark
        if lt or gt:
            await self._event.wait()

    def __repr__(self):
        return f"<WatermarkQueue qsize={self.qsize()}>"
