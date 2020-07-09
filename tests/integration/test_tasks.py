import pytest

from tests.helpers.waiting import wait_atleast, wait_done, wait_started
from tests.helpers.worker import worker


@pytest.mark.asyncio
async def test_task(app, results):
    @app.task
    async def incr():
        await results.incr()

    async with worker(app) as w:
        await wait_started(w)
        await wait_done(results, count=1, delay=1)


@pytest.mark.asyncio
async def test_timer(app, results):
    @app.timer(interval=0.01)
    async def incr():
        await results.incr()

    async with worker(app) as w:
        await wait_started(w)
        await wait_atleast(results, count=20, delay=1)


@pytest.mark.asyncio
async def test_crontab(mocker, app, results):
    mocked_seconds_until = mocker.patch("runnel.app.seconds_until")
    mocked_seconds_until.return_value = 0.01

    @app.crontab("* * * * *")
    async def incr():
        await results.incr()

    async with worker(app) as w:
        await wait_started(w)
        await wait_atleast(results, count=1, delay=1)
