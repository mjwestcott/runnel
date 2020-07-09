class RunnelException(Exception):
    pass


class Misconfigured(RunnelException):
    pass


class RebalanceFailed(RunnelException):
    pass


class NoPartitionsAssigned(RunnelException):
    pass


class AcquirePartitionLockFailed(RunnelException):
    pass


class ExtendPartitionLockFailed(RunnelException):
    pass
