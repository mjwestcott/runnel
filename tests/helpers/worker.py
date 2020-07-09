from contextlib import asynccontextmanager

import anyio

from runnel.worker import Worker


@asynccontextmanager
async def worker(app):
    w = Worker(app)

    async with anyio.create_task_group() as tg:
        await tg.spawn(w._start)
        yield w
        await tg.cancel_scope.cancel()


@asynccontextmanager
async def workers(app, count=2):
    ws = [Worker(app) for _ in range(count)]

    async with anyio.create_task_group() as tg:
        for w in ws:
            await tg.spawn(w._start)
        yield ws
        await tg.cancel_scope.cancel()
