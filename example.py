from datetime import datetime
from typing import List

from runnel import App, Record

app = App(name="example")


# Structured event types can be specified using the Record class. They will be
# serialised and stored in a single field in the stream.
class Order(Record):
    order_id: int
    created_at: datetime
    amount: int
    item_ids: List[int]


orders = app.stream("orders", record=Order, partition_by="order_id")


@app.processor(orders)
async def printer(events):
    async for order in events.records():
        print(order.amount)


# You can opt out of complex records and use the native Redis key-value stream type by
# setting primitive=True. This allows you to benefit from optimisations such as delta
# compression (see http://antirez.com/news/128), at the cost of not supporting nested
# values.
class UserAction(Record, primitive=True):
    user_id: int
    type: str


actions = app.stream("actions", record=UserAction, partition_by="user_id")


@app.processor(actions)
async def extractor(events):
    async for action in events.records():
        print(action.user_id)
