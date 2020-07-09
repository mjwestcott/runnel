Architecture
============

This document describes the under-the-hood architecture in detail. For a guide on how to
use this library, see the :ref:`Guide` instead.

Sending Events
--------------

Events are stored in a set of Redis keys. One :attr:`runnel.App.stream` corresponds to
many Redis stream data structures, controlled by the ``partition_count`` setting. They
can be sent from your Python application code via :meth:`runnel.Stream.send` or from the
shell via the CLI :attr:`runnel.cli.send` or :attr:`runnel.cli.sendmany` commands. For
every record to send, the correct partition is computed by hashing the ``partition_key``.
Each partition has a maximum length, controlled by the ``partition_size`` setting. It is
implemented using the ``MAXLEN`` option to ``XADD`` (see the `Redis docs
<https://redis.io/commands/xadd>`_).

Processing Events
-----------------

Events are then processed by your :attr:`runnel.App.processor` functions, which are run
by workers. This is the detailed breakdown of entities spawned by a single worker (each
box is implemented as an `asyncio task <https://docs.python.org/3/library/asyncio.html>`_):

.. image:: _static/runnel-task-graph.png

Worker: Created by running ``$ runnel worker`` in your shell. By default, will create an
Executor for every processor you have created in your runnel application. (But you can
specify a subset of processors if you wish, see :attr:`runnel.cli.worker`.)

Leadership: A periodic task to choose a worker to become the 'leader', which means it is
responsible for running background tasks for which ``on_leader=True``.

Executors: Responsible for executing a user-provided :attr:`runnel.App.processor`
function over partitions of the stream. Newly created executors will trigger a
:ref:`Rebalance` so that partitions are evenly distributed between workers. Will acquire
locks implemented in Redis for every partition it is assigned.

Heartbeat: A periodic task to emit a heartbeat (stored in Redis) every so often, to
communicate to other workers that it is alive and well. If an executor's heartbeat
expires, it will be considered dead and its partitions will be reassigned to other
workers. Also responsible for extending the executors' partition locks.

Maintenance: A periodic task to check whether any other workers have died, in which case
a :ref:`Rebalance` is triggered.

Control: Listens for messages in a 'control' stream in Redis which announces the
creation and departure of workers. Notifies the executor that a :ref:`Rebalance` should
begin.

Runner: Responsible for concurrently running one Fetcher and multiple Consumers (one for
every partition of the stream currently owned by the Executor).

Fetcher: A long-running task to retrieve events from Redis. Spawns multiple Fetch tasks.

Fetch: A task which calls the Redis `XREADGROUP <https://redis.io/commands/xreadgroup>`_
command to retrieve events from a set of partitions and store them in internal buffers.
Will block if no events are currently pending.

Consumers: Each of these tasks calls the user-provided :attr:`runnel.App.processor`
function for a single partition of the stream, passing it an Events generator.
Responsible for implementing the exception policy (see :ref:`Exception handling`) in
case the processor function fails.

Processor: The user-provided processor function, responsible for iterating over the
Events generator and performing arbitrary logic. Each task will receive events for a
single partition of the stream.

Events: A generator of events, passed to the user-provided :attr:`runnel.App.processor`
function. Will retrieve events that have been fetched from Redis from an internal
buffer, pass them through any :attr:`runnel.interfaces.Middleware` defined for the
stream, yield them, and then `XACK <https://redis.io/commands/xack>`_ them so they are
processed only once.

Waiter: A task which waits for a signal to shutdown a Consumer. It will be triggered if
the consumer's partition is no longer owned by this Executor due to a :ref:`Rebalance`.

Redis Keys
----------

Assume that we are running the following application:

.. code-block:: python

    from runnel import App, Record


    app = App(name="myapp", redis_url="redis://127.0.0.1")


    class Order(Record):
        order_id: int
        amount: int


    orders = app.stream("orders", record=Order, partition_by="order_id")


    @app.processor(orders)
    async def printer(events):
        async for order in events.records():
            print(order.amount)


The following Redis keys will be used:

``__strm:example.orders.{partition_number}``
    The partitioned stream data structures for events. `partition_number` is an integer
    from 0 to 1-`partition_count`.

``__memb:example.orders.printer``
    A string key holding JSON-encoded membership data for existing executors. Contains
    the mapping from executors to the partitions they have been assigned.

``__ctrl:example.orders.printer``
    A stream for communicating control messages between executors. Used to announce
    joining/leaving workers which triggers a rebalance.

``__lock:example.orders.printer.{partition_number}``
    A lock for every stream partition. Should be owned by the assigned executor. Must be
    owned before processing a partition.

``__lock:example.orders.printer.admin``
    A lock to protect atomic admin operations, such as changing the partition
    assignments.

``__beat:example.orders.printer.{executor_id}``
    An expiring string key to indicate that an executor is still alive. `executor_id` is
    a uuid.

``__lead:example``
    Holds the name of the current lead worker, which is responsible for running
    background tasks for which ``on_leader=True``.
