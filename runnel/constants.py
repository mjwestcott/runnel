from enum import Enum, unique


@unique
class Rebalance(str, Enum):
    JOIN = "join"
    LEAVE = "leave"
    DEAD = "dead"

    def message(self, **kwargs):
        return dict(reason=self.value, **kwargs)


@unique
class ExceptionPolicy(str, Enum):
    """
    An enum specifying how to handle exceptions raised in the user-provided processor
    coroutine.

    * ``HALT``: Raise the exception, halting execution of the affected partition.
    * ``QUARANTINE``: Mark the affected partition as poisoned, and continue with others.
    * ``IGNORE``: Suppress the exception and continue processing regardless.

    Examples
    --------
    >>> @app.processor(orders, exception_policy=ExceptionPolicy.HALT)
    ... async def printer(events):
    ...     async for order in events.records():
    ...         print(order.amount)
    """
    HALT = "halt"
    QUARANTINE = "quarantine"
    IGNORE = "ignore"
