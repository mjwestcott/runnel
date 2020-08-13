import json
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from typing import TYPE_CHECKING, Coroutine, Dict, List

import structlog
from aredis.exceptions import RedisError

from runnel.constants import ExceptionPolicy, Rebalance
from runnel.exceptions import Misconfigured
from runnel.utils import chunks

if TYPE_CHECKING:
    from runnel.stream import Stream
    from runnel.interfaces import Middleware

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class Processor:
    """
    A wrapper around a Python function which iterates over a continuous event stream.

    A processor will be run by one or more executors. Each executor will be responsible
    for processing a different subset of partitions of the underlying Redis streams.

    Not intended to be used directly. Use :attr:`runnel.App.processor` instead.
    """
    stream: "Stream"
    f: Coroutine
    name: str
    exception_policy: ExceptionPolicy
    middleware: List["Middleware"]
    lock_expiry: int
    read_timeout: int
    prefetch_count: int
    assignment_attempts: int
    assignment_sleep: float
    grace_period: float
    pool_size: int
    join_delay: int

    def __post_init__(self):
        if self.read_timeout > self.grace_period * 1000:
            raise Misconfigured("read_timeout must be less than grace_period")

    def __hash__(self):
        return hash(self.id)

    async def __call__(self, *args, **kwargs):
        await self.f(*args, **kwargs)

    @property
    def app(self):
        return self.stream.app

    @property
    def id(self):
        return f"{self.stream.id}.{self.name}"

    @property
    def group(self):
        # The consumer group identity in Redis.
        return self.name

    @property
    def consumer(self):
        # The consumer group consumer identity in Redis. (There is only ever
        # a single consumer since our raison d'etre is in-order processing,
        # not fanning-out a single partition to multiple consumers.)
        return "1"

    @property
    def members_key(self):
        return f"__memb:{self.id}"

    @lru_cache
    def heartbeat_key(self, executor_id):
        return f"__beat:{self.id}.{executor_id}"

    @property
    def control_key(self):
        return f"__ctrl:{self.id}"

    def lock_key(self, name):
        assert name == "admin" or isinstance(name, int)
        return f"__lock:{self.id}.{name}"

    @asynccontextmanager
    async def admin_lock(self):
        timeout = self.app.settings.default_lock_expiry
        async with self.app.redis.lock(self.lock_key("admin"), timeout=timeout):
            yield

    async def members(self):
        return await self.app.redis.get(self.members_key)

    async def maybe_join(self, executor_id: str):
        await self.rebalance(Rebalance.JOIN, executor_id)

    async def maybe_leave(self, executor_id: str):
        await self.rebalance(Rebalance.LEAVE, executor_id)

    async def read_control_messages(self, start="$", timeout=4000):
        while True:
            results = await self.app.redis.xread(
                count=1,
                block=timeout,
                **{self.control_key: start},
            )
            for stream, result in results.items():
                assert stream.decode("utf-8") == self.control_key
                for xid, data in result:
                    yield data
                    start = xid

    async def send_control_message(self, **kwargs):
        await self.app.redis.xadd(self.control_key, kwargs, max_len=256)

    async def rebalance(self, reason: Rebalance, executor_id: str):
        async with self.admin_lock():
            members = json.loads(await self.members() or "{}")

            if reason == Rebalance.JOIN and executor_id in members:
                return
            if reason == Rebalance.LEAVE and executor_id not in members:
                return

            new = self._rebalance(reason, members, executor_id)
            logger.info("reassigning-partitions", new=new)
            await self.app.redis.set(self.members_key, json.dumps(new))

        msg = reason.message(executor_ids=json.dumps([executor_id]))
        await self.send_control_message(**msg)

    def _rebalance(self, reason, members: Dict, executor_id):
        executors = {x: members[x]["joined_at"] for x in members}

        if reason == Rebalance.JOIN:
            executors[executor_id] = datetime.utcnow().isoformat()
        elif reason == Rebalance.LEAVE:
            del executors[executor_id]
        else:
            raise ValueError(f"unexpected rebalance reason: {reason}")

        return self._compute_assignments(executors)

    async def reap(self):
        # Check for any executors who exist in the members list, but whose heartbeat has
        # expired -- they are considered dead. They must be removed from the list and
        # their partitions reassigned to other members.
        async with self.admin_lock():
            members = json.loads(await self.members() or "{}")
            if members:
                new = await self._reap(members)
                if new:
                    logger.critical("dead-executor-found", new=new)
                    await self.app.redis.set(self.members_key, json.dumps(new))
                    dead = [x for x in members if x not in new]
                    msg = Rebalance.DEAD.message(executor_ids=dead)
                    await self.app.redis.publish(self.control_key, msg)

    async def _reap(self, members):
        keys = [self.heartbeat_key(x) for x in members]
        heartbeats = await self.app.redis.mget(keys)
        alive = {x: members[x]["joined_at"] for x, found in zip(members, heartbeats) if found}

        if all(k in alive for k in members):
            return
        return self._compute_assignments(alive)

    def _compute_assignments(self, executors: Dict[str, str]):
        # This function takes a mapping from executor_ids to their join times and returns
        # a new members dictionary including the partition assignments. A naive random
        # assignment would result in large changes every time an executor joins. Using
        # consistent hashing would minimise changes, but can suffer from an uneven
        # distribution of partitions. Instead we order executors by their join date and
        # split partitions evenly. This results in more changes than necessary -- O(n)
        # rather than O(m/n) where n=executors m=partitions -- but gives us perfect
        # fairness, which is more important given our small number of partitions.
        return {
            executor_id: {
                "joined_at": executors[executor_id],
                "partitions": chunk,
            }
            for executor_id, chunk in zip(
                sorted(executors, key=lambda e: executors[e]),
                chunks(list(range(0, self.stream.partition_count)), len(executors))
            )
        }

    async def group_setid(self, start):
        keys = self.stream.all_partition_keys()
        cmds = [("XGROUP", "SETID", key, self.group, start) for key in keys]
        async with await self.app.redis.pipeline() as pipe:
            for cmd in cmds:
                await pipe.execute_command(*cmd)
            await pipe.execute()

    async def group_destroy(self):
        keys = self.stream.all_partition_keys()
        cmds = [("XGROUP", "DESTROY", key, self.group) for key in keys]
        async with await self.app.redis.pipeline() as pipe:
            for cmd in cmds:
                await pipe.execute_command(*cmd)
            await pipe.execute()

    async def group_create(self, start="0"):
        keys = self.stream.all_partition_keys()
        cmds = [("XGROUP", "CREATE", key, self.group, start, "MKSTREAM") for key in keys]
        async with await self.app.redis.pipeline() as pipe:
            for cmd in cmds:
                await pipe.execute_command(*cmd)
            await pipe.execute()

    async def group_exists(self):
        keys = self.stream.all_partition_keys()
        try:
            # Just check the last one, since they are either all created or none.
            info = await self.app.redis.xinfo_groups(keys[-1])
            return self.group.encode("utf-8") in {x[b"name"] for x in info}
        except RedisError as e:
            assert str(e) == "no such key"
            return False

    async def prepare(self):
        """
        Run XGROUP CREATE for all partitions of this processor's stream, if they do not
        already exist.
        """
        async with self.admin_lock():
            if not await self.group_exists():
                await self.group_create()

    async def reset(self, start):
        """
        Run XGROUP DESTORY (if the group exists) followed by XGROUP CREATE with the
        given starting id for all partitions of this processor's stream.

        This should be executed once all workers have been shut down. It will purge any
        unacked events from the 'pending entries list' and will start over from scratch.

        Parameters
        ----------
        start : str
            The starting ID argument to XGROUP CREATE, see https://redis.io/commands/xgroup
        """
        async with self.admin_lock():
            if await self.group_exists():
                await self.group_destroy()
            await self.group_create(start)
