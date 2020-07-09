from pydantic import BaseModel

from runnel.exceptions import Misconfigured


class Record(BaseModel):
    def __init__(self, *args, **kwargs):
        """
        This class is used to specify structured data types to store in streams.

        It is a specialized version of pydantic.BaseModel, see
        https://pydantic-docs.helpmanual.io/ for more information.

        Examples
        --------
        >>> class Order(Record):
        ...     order_id: int
        ...     created_at: datetime
        ...     amount: int
        ...     item_ids: List[int]

        Records can be nested arbitrarily, e.g. `items: List[Item]` where `Item` is
        another record. They will be serialized (according to the serializer/compressor
        settings) and stored as arbitrary bytes as a single value in a Redis stream
        entry.

        Alternatively, you can use the native Redis stream key/value pairs by setting
        primitive=True, e.g.:

        >>> class UserAction(Record, primitive=True):
        ...     user_id: int
        ...     type: str

        This allows you to benefit from optimisations such as delta compression (see
        http://antirez.com/news/128), at the cost of not supporting nested values. Only
        int, float, bool, str, and bytes are allowed.
        """
        super().__init__(*args, **kwargs)

    def __init_subclass__(cls, /, primitive=False, **kwargs):
        super().__init_subclass__(**kwargs)
        cls._primitive = primitive

        if primitive:
            allowed = {int, float, bool, str, bytes}
            if not set(cls.__annotations__.values()) <= allowed:
                raise Misconfigured(f"Primitive record fields must be in {allowed}")
