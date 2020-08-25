import os
from itertools import count

import aredis
import pytest

from runnel import App
from runnel.logging import init_logging
from runnel.settings import Settings
from tests.helpers.records import Order
from tests.helpers.results import Results

init_logging()


def pytest_addoption(parser):
    parser.addoption("--runslow", action="store_true", help="run slow tests")


def pytest_runtest_setup(item):
    if "slow" in item.keywords and not item.config.getoption("--runslow"):
        pytest.skip("need --runslow option to run")


# https://anyio.readthedocs.io/en/latest/testing.html
@pytest.fixture(autouse=True)
def anyio_backend():
    return ('asyncio', {'use_uvloop': True})


@pytest.fixture(scope="session")
def seq():
    return count()


@pytest.fixture(scope="session")
def settings():
    os.environ["RUNNEL_TESTING"] = "1"
    return Settings()


@pytest.fixture(autouse=True)
async def redis(settings):
    client = aredis.StrictRedis.from_url(settings.redis_url)
    await client.flushall()
    try:
        yield client
    finally:
        await client.flushall()


@pytest.fixture
def app(seq):
    return App(
        name=f"testapp-{next(seq)}",
        default_partition_count=8,
        default_lock_expiry=2,
        default_grace_period=1,
        default_read_timeout=50,
        default_prefetch_count=4,
        default_assignment_sleep=0.4,
        default_assignment_attempts=128,
        default_pool_size=2,
        default_join_delay=0,
    )


@pytest.fixture
def stream(app):
    return app.stream("teststream", record=Order, partition_by="id")


@pytest.fixture
def results(redis):
    return Results(redis)
