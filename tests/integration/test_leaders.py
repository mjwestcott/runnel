import asyncio

import anyio

from runnel import App, context
from tests.helpers.processes import subprocess
from tests.helpers.results import Results
from tests.helpers.waiting import wait_atleast, wait_done, wait_started
from tests.helpers.worker import workers


async def test_task(app, results):
    @app.task(on_leader=True)
    async def incr():
        await results.set(context.worker_id.get(), True)
        await results.incr()

    async with workers(app, count=3) as ws:
        await wait_started(*ws)
        await wait_done(results, count=1, delay=1)
        await asyncio.sleep(0.1)

        # Ensure it only ran on the leader.
        assert len(await results.values()) == 1


async def test_timer(app, results):
    @app.timer(interval=0.01, on_leader=True)
    async def incr():
        await results.set(context.worker_id.get(), True)
        await results.incr()

    async with workers(app, count=3) as ws:
        await wait_started(*ws)
        await wait_atleast(results, count=20, delay=1)
        await asyncio.sleep(0.1)

        # Ensure it only ran on the leader.
        assert len(await results.values()) == 1


async def test_crontab(mocker, app, results):
    mocked_seconds_until = mocker.patch("runnel.app.seconds_until")
    mocked_seconds_until.return_value = 0.01

    @app.crontab("* * * * *", on_leader=True)
    async def incr():
        await results.set(context.worker_id.get(), True)
        await results.incr()

    async with workers(app, count=3) as ws:
        await wait_started(*ws)
        await wait_atleast(results, count=1, delay=1)
        await asyncio.sleep(0.1)

        # Ensure it only ran on the leader.
        assert len(await results.values()) == 1


# At the module level because we will import it via the CLI from a subprocess.
app = App(
    name="tests.integration.test_leaders:app",
    leadership_poll_interval=100,
)


@app.timer(interval=0.1, on_leader=True)
async def task():
    results = Results(app.redis)
    await results.set(context.worker_id.get(), True)


async def test_tasks_continue_after_leader_change(results):
    """
    Ensure that existing workers can become leader and continue processing background
    tasks after the first fails.
    """
    async def wait_for_leader(n):
        while not len(await results.values()) == n:
            await asyncio.sleep(0.02)

    async with anyio.fail_after(3):
        with subprocess(app.name) as p1:
            await wait_for_leader(1)
            with subprocess(app.name):
                await asyncio.sleep(0.1)
                p1.kill()
                await wait_for_leader(2)
