import asyncio

from runnel.concurrency import race


async def test_race():
    async def coro1(duration):
        await asyncio.sleep(duration)
        return 1

    async def coro2(duration):
        await asyncio.sleep(duration)
        return 2

    assert await race(coro1(0), coro2(10)) == 1
    assert await race(coro1(10), coro2(0)) == 2
