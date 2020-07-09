from functools import lru_cache
from hashlib import md5

try:
    from xxhash import xxh32
except ImportError:
    xxh32 = None


@lru_cache
def md5hash(x):
    return int(md5(repr(x).encode("utf-8")).hexdigest(), 16)


@lru_cache
def fasthash(x):
    return xxh32(repr(x)).intdigest()


if xxh32:
    default = fasthash
else:
    default = md5hash
