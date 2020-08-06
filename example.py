from datetime import datetime

from runnel import App, Record

app = App(name="example")


# Structured event types can be specified using the Record class. They will be
# serialised and stored in a single field in the stream.
class Order(Record):
    order_id: int
    created_at: datetime
    amount: float


orders = app.stream("orders", record=Order, partition_by="order_id")


# Every 4 seconds, send an example record to the stream.
@app.timer(interval=4)
async def sender():
    await orders.send(Order(order_id=1, created_at=datetime.utcnow(), amount=9.99))


# Run the app from the CLI via `$ runnel worker example:app`
@app.processor(orders)
async def printer(events):
    async for order in events.records():
        print(f"processed {order.amount}")
