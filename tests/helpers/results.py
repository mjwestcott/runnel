from dataclasses import dataclass

import aredis


@dataclass
class Results:
    redis: aredis.StrictRedis

    async def incr(self, by=1):
        return await self.redis.incr("__test-count", amount=by)

    async def count(self):
        return int(await self.redis.get("__test-count") or "0")

    async def set(self, key, value):
        return await self.redis.hset("__test-values", key, value)

    async def get(self, key):
        return await self.redis.hget("__test-values", key)

    async def values(self):
        return await self.redis.hgetall("__test-values")
