Introduction
============

Runnel is a distributed event processing framework for Python based on Redis Streams.

Whereas traditional job queues do not provide ordering guarantees, Runnel is designed to
process partitions of your event stream strictly in the order events are created.


Basic Usage
-----------

.. code-block:: python

    from datetime import datetime
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

Meanwhile, run the worker (assuming code in `example.py`):

.. code-block:: bash

    $ runnel worker example:app

And send some events:

.. code-block:: bash

    $ runnel send example:orders "{\"order_id\": 1, \"created_at\": \"2020-07-21T22:09:37Z\" , \"amount\": 99}"


Features
--------

Runnel was designed to support a similar paradigm to Kafka Streams, but on top of Redis.

* At least once processing semantics
* Automatic partitioning of events by key
* Each partition maintains strict ordering
* Dynamic rebalance algorithm distributes partitions among workers on-the-fly
* Support for nested Record types with custom serialisation and compression
* Background tasks, including timers and cron-style scheduling
* User-defined middleware for exception handling, e.g. dead-letter-queueing
* A builtin batching mechanism to efficiently process events in bulk
* A ``runnel[fast]`` bundle for C or Rust extension dependencies (`uvloop <https://github.com/MagicStack/uvloop>`_, `xxhash <https://github.com/Cyan4973/xxHash>`_, `orjson <https://github.com/ijl/orjson>`_, `lz4 <https://github.com/python-lz4/python-lz4>`_)


Contents
--------

.. toctree::
   :maxdepth: 2

    Guide <guide>
    Installation <installation>
    Motivation <motivation>
    Architecture <architecture>
    Rebalance <rebalance>
    API Reference <reference>
    CLI <cli>


Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
