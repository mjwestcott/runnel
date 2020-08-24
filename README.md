## Runnel

Distributed event processing for Python based on Redis Streams.

https://runnel.dev

Runnel allows you to easily create scalable stream processors, which operate on
partitions of event streams in Redis. Runnel takes care of assigning partitions
to workers and acknowledging events automatically, so you can focus on your
application logic.

Whereas traditional job queues do not provide ordering guarantees, Runnel is
designed to process partitions of your event stream strictly in the order
events are created.

### Installation

```bash
pip install runnel
```

### Basic Usage

```python
from datetime import datetime

from runnel import App, Record

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
```

Meanwhile, run the worker (assuming code in `example.py` and `PYTHONPATH` is set):
```bash
$ runnel worker example:app
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

### Documentation

Full documenation is available at https://runnel.dev.

* [Guide](https://runnel.dev/guide.html)
* [Motivation](https://runnel.dev/motivation.html)
* [Architecture](https://runnel.dev/architecture.html)
* [API Reference](https://runnel.dev/reference.html)

### Blog posts

Essays about this project or the technology it's using:

* [Redis streams vs. Kafka](https://mattwestcott.co.uk/blog/redis-streams-vs-kafka)
* [Structured concurrency in Python with AnyIO](https://mattwestcott.co.uk/blog/structured-concurrency-in-python-with-anyio)

### Local development

To run the test suite locally, clone the repo and install the optional deps
(e.g. via `poetry install -E fast`). Make sure Redis is running on localhost at
port 6379, then run `pytest`.

### See also

For a traditional task queue that doesn't provide ordering guarantees, see our
sister project [Fennel](https://github.com/mjwestcott/fennel).
