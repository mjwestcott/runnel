from datetime import datetime

from runnel import App, Record

# Run this app from the CLI via `$ runnel worker example:app`
app = App(name="myapp", redis_url="redis://127.0.0.1")


# Specify event types using the Record class.
class Order(Record):
    order_id: int
    created_at: datetime
    amount: float


orders = app.stream("orders", record=Order, partition_by="order_id")


# Every 4 seconds, send an example record to the stream.
@app.timer(interval=4)
async def sender():
    await orders.send(Order(order_id=1, created_at=datetime.utcnow(), amount=9.99))


# Iterate over a continuous stream of events in your processors.
@app.processor(orders)
async def printer(events):
    async for order in events.records():
        print(f"processed {order.amount}")
