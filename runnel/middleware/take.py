from dataclasses import dataclass

import anyio
import structlog

from runnel.interfaces import Middleware

logger = structlog.get_logger(__name__)


@dataclass
class Take(Middleware):
    n: int
    within: float

    async def handler(self, parent, events, **kwargs):
        send_stream, receive_stream = anyio.create_memory_object_stream(self.n)
        produced, consumed = anyio.create_event(), anyio.create_event()

        async with anyio.create_task_group() as tg:
            await tg.spawn(self._producer, parent, send_stream, produced, consumed)

            while True:
                async with anyio.move_on_after(self.within):
                    await produced.wait()

                while receive_stream._state.buffer:
                    try:
                        yield await self._consume(receive_stream)
                    # https://github.com/python-trio/trio/issues/638#issuecomment-418588615
                    except GeneratorExit:
                        await tg.cancel_scope.cancel()
                        logger.warning("take-middleware-exit")
                        return

                await consumed.set()
                consumed = anyio.create_event()
                produced = anyio.create_event()

    async def _producer(self, parent, send_stream, produced, consumed):
        async for event in parent:
            await send_stream.send(event)

            if len(send_stream._state.buffer) == self.n:
                await produced.set()
                await consumed.wait()

    async def _consume(self, receive_stream):
        batch = []
        for _ in range(self.n):
            try:
                batch.append(await receive_stream.receive_nowait())
            except anyio.WouldBlock:
                logger.debug("took-too-few", have=len(batch), wanted=self.n)
                break
        logger.debug("take-consumed", batch=[e.data for e in batch])
        return batch
