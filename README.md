## Runnel

Distributed event processing for Python based on Redis Streams.

Runnel allows you to easily create scalable stream processors, which operate on
partitions of event streams in Redis. Runnel takes care of assigning partitions
to workers and acknowledging events automatically, so you can focus on your
application logic.

Whereas traditional job queues do not provide ordering guarantees, Runnel is
designed to process partitions of your event stream strictly in the order
events are created.

### Basic Usage

```python
from runnel import App, Record


app = App(name="myapp", redis_url="redis://127.0.0.1")


class Order(Record):
    order_id: int
    created_at: datetime
    amount: int


orders = app.stream("orders", record=Order, partition_by="order_id")


@app.processor(orders)
async def printer(events):
    async for order in events.records():
        print(order.amount)
```

Meanwhile, run the worker (assuming code in `example.py`):
```bash
$ runnel worker example:app
```

And send some events:
```bash
$ runnel send example:orders "{\"order_id\": 1, \"created_at\": \"2020-07-21T22:09:37Z\" , \"amount\": 99}"
```

### Features

Designed to support a similar paradigm to Kafka Streams, but on top of Redis.

* At least once processing semantics
* Automatic partitioning of events by key
* Each partition maintains strict ordering
* Dynamic rebalance algorithm distributes partitions among workers on-the-fly
* Support for nested Record types with custom serialisation and compression
* Background tasks, including timers and cron-style scheduling
* User-defined middleware for exception handling, e.g. dead-letter-queueing
* A builtin batching mechanism to efficiently process events in bulk
* A `runnel[fast]` bundle for C or Rust extension dependencies ([uvloop](https://github.com/MagicStack/uvloop), [xxhash](https://github.com/Cyan4973/xxHash), [orjson](https://github.com/ijl/orjson), [lz4](https://github.com/python-lz4/python-lz4))

### Installation

```bash
pip install runnel
```
