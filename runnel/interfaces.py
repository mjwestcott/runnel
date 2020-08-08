from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, AsyncIterator, List, Union

if TYPE_CHECKING:
    from runnel.types import Event


class Compressor:
    """
    Implement this interface to customise event data compression.

    Examples
    --------
    >>> import gzip
    ...
    >>> class Gzip(Compressor):
    ...     def compress(self, value):
    ...         return gzip.compress(value)
    ...
    ...     def decompress(self, value):
    ...         return gzip.decompress(value)

    Then configure your serializer to use it:

    >>> from runnel import App, Record, JSONSerializer
    ...
    >>> app = App(name="example")
    ...
    >>> class Order(Record):
    ...     order_id: int
    ...     amount: int
    ...
    >>> orders = app.stream(
    ...     name="orders",
    ...     record=Order,
    ...     partition_by="order_id",
    ...     serializer=JSONSerializer(compressor=Gzip()),
    ... )
    """
    def compress(self, value: bytes) -> bytes:
        """Return compressed bytes."""
        raise NotImplementedError

    def decompress(self, value: bytes) -> bytes:
        """Return decompressed bytes."""
        raise NotImplementedError


@dataclass(frozen=True)
class Serializer:
    """
    Implement this interface to customise event data serialization.

    Examples
    --------
    >>> import orjson  # A fast JSON library written in Rust.
    ...
    >>> @dataclass(frozen=True)
    >>> class FastJSONSerializer(Serializer):
    >>>     compressor = None
    ...
    ...     def dumps(self, value):
    ...         return orjson.dumps(value)
    ...
    ...     def loads(self, value):
    ...         return orjson.loads(value)

    Then pass it to your stream:

    >>> from runnel import App, Record
    ...
    >>> app = App(name="example")
    ...
    >>> class Order(Record):
    ...     order_id: int
    ...     amount: int
    ...
    >>> orders = app.stream(
    ...     name="orders",
    ...     record=Order,
    ...     partition_by="order_id",
    ...     serializer=FastJSONSerializer(),
    ... )
    """
    compressor: Compressor = None

    def dumps(self, value: Any) -> bytes:
        """Return serialized bytes."""
        raise NotImplementedError

    def loads(self, value: bytes) -> Any:
        """Return deserialized Python object."""
        raise NotImplementedError


class Middleware:
    """
    Middleware are objects with a `handler` method (decribed below). Processors accept
    a list of user-provided middleware.

    The handler methods form a processing pipeline which runs over events before they
    are yielded to the final processor function. Each handler is passed the previous
    handler in the pipeline (called 'parent').

    Examples
    --------
    >>> from runnel.interfaces import Middleware
    ...
    >>> class Printer(Middleware):
    ...     async def handler(self, parent, **kwargs):
    ...         async for x in parent:
    ...             print(x)
    ...             yield x

    It can then be passed to the processor.

    >>> @app.processor(mystream, middleware=[Printer()])
    ... async def proc(events):
    ...     async for record in events.records():
    ...         pass

    Notes
    -----
    Some of Runnel's internal functionality is implemented using middleware. They can be
    found `here <https://github.com/mjwestcott/runnel/tree/master/runnel/middleware>`_.
    """
    async def handler(self, parent, **kwargs) -> AsyncIterator[Union["Event", List["Event"]]]:
        """
        A middleware handler is an async generator. Given a parent generator that yields
        Events or batches of Events, it must yield the same.

        For example:

        >>> async for x in parent:
        ...     assert isinstance(x, (Event, list))
        ...     yield x

        Post-processing logic can be added below, in a finally clause. This allows you
        to respond to errors further up the chain (e.g. in the final processor code):

        >>> async for x in parent:
        ...     try:
        ...         yield x
        ...     finally:
        ...         await logic()

        This is needed because a GeneratorExit exception will be thrown into the yield
        point if an exception is raised in the calling code. (Also note that async
        generator finalization is scheduled by the Python runtime asynchronously, but
        the Runnel framework ensures it has finished before restarting a processor
        function.)

        If you only want to know if an exception was raised further up the chain, you
        can use the following:

        >>> async for x in parent:
        ...     try:
        ...         yield x
        ...     except GeneratorExit:
        ...         await cleanup()
        ...         raise

        (Note: Python requires that GeneratorExit it not ignored, so it must be reraised
        here to avoid a RuntimeError)
        """
        raise NotImplementedError
