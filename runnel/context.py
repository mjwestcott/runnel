from contextvars import ContextVar

worker_id = ContextVar("worker_id", default=None)
executor_id = ContextVar("executor_id", default=None)
stream = ContextVar("stream", default=None)
partition_id: ContextVar[int] = ContextVar("partition_id", default=None)
