from functools import lru_cache

import anyio
import structlog

from tests.exceptions import MoreThanOnce, Never, TooManyResults

logger = structlog.get_logger(__name__)


@lru_cache(maxsize=2**16)
def event_id(i):
    return f"__event:{i}__"


async def wait_started(*workers, delay=2):
    async with anyio.fail_after(delay):
        for w in workers:
            while not w.started:
                await anyio.sleep(0.005)


async def wait_running(*workers, delay=2):
    async with anyio.fail_after(delay):
        for w in workers:
            while not w.started:
                await anyio.sleep(0.005)
            for e in w.executors:
                await e.wait_for(lambda: e.rebalanced)


async def wait_done(results, count, delay=2, debug_key=None):
    async def _wait():
        async with anyio.fail_after(delay):
            while True:
                found = await results.count()

                if found == count:
                    return
                elif found > count:
                    raise TooManyResults(f"{found} > {count}")
                else:
                    await anyio.sleep(0.05)

    if debug_key:
        try:
            await _wait()
        except TooManyResults:
            for i in range(count):
                if int(await results.redis.get(debug_key(i)) or b'0') > 1:
                    raise MoreThanOnce(debug_key(i))
        except TimeoutError:
            for i in range(count):
                if not await results.redis.get(debug_key(i)):
                    raise Never(debug_key(i))
    else:
        await _wait()


async def wait_atleast(results, count, delay=2, sleep=0.05):
    async with anyio.fail_after(delay):
        while True:
            found = await results.count()

            if found >= count:
                return await results.values()
            else:
                await anyio.sleep(sleep)
