Guide
=====

Runnel is a distributed event processing framework for Python based on Redis Streams.

It allows you to easily create scalable stream processors, which operate on strictly
ordered partitions of event streams. Runnel takes care of assigning partitions to
workers, and acknowledging events automatically, so you can focus on your application
logic.

Whereas traditional job queues do not provide ordering guarantees, Runnel is designed to
process partitions of your event stream strictly in the order events are created.


The App
-------

.. code-block:: python

    from runnel import App


    app = App(name="myapp", redis_url="redis://127.0.0.1")


The app is the starting point for your Runnel project. You need provide a name and a
Redis URL. You will use it to define event streams and processors. Workers will run your
app.

The full set of kwargs can be found at :attr:`runnel.settings.Settings`. The settings
can be provided as environment variables, e.g. ``RUNNEL_LOG_LEVEL=debug`` or as kwargs
to the app instance. Many of the settings are defaults and can be overridden on the
stream or processor objects you will create.


Defining your event stream
--------------------------

Structured records
~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from datetime import datetime

    from runnel import Record


    class Order(Record):
        order_id: int
        created_at: datetime
        amount: float


The Record class allows you to specify structured event types to be stored in your
stream. It is implemented using `Pydantic <https://pydantic-docs.helpmanual.io/>`_ and
they can be nested arbitrarily:


.. code-block:: python

    class Item(Record):
        id: int
        name: str


    class Order(Record):
        id: int
        name: str
        items: List[Item]


Redis streams are key-value data structures, storing both as bytes. By default, your
records will be JSON-serialized to bytes and stored under a single 'data' key in the
stream. This is a flexible solution and allows you to optionally compress your records
too.

You can provide your own serialisation and compression implementations (see
:attr:`runnel.interfaces`)


Primitive records
~~~~~~~~~~~~~~~~~

.. code-block:: python

    class Order(Record, primitive=True):
        order_id: int
        complete: bool
        purchased_by: str


You can opt out of complex records and use the native Redis key-value stream type by
setting ``primitive=True``. This allows you to benefit from optimisations such as delta
compression (see http://antirez.com/news/128), at the cost of not supporting nested
values. Primitive records only support fields of ``int``, ``float``, ``bool``, ``str``,
and ``bytes``.


The stream
~~~~~~~~~~

.. code-block:: python

    orders = app.stream("orders", record=Order, partition_by="order_id")


An example stream is defined above. You need to give it a name, specify the Record type,
and pick a field to partition by. When you create an event, Runnel will use your
stream's ``hasher`` to hash the chosen partition key and compute which partition to send
it to.

You can specify the stream's ``partition_count``. This controls the degree of
parallelism in your processing. Every partition will be processed by a separate instance
of your processor code. If you run multiple workers, the partitions will be distributed
evenly between them. To maintain strictly ordered processing, only one processor will
process a partition at one time.

The stream's ``partition_size`` controls the maximum length of each partition's stream.
It is implemented using the ``MAXLEN`` option to ``XADD`` (see the `Redis docs
<https://redis.io/commands/xadd>`_).


How to send events
~~~~~~~~~~~~~~~~~~

Events can be sent as follows:

.. code-block:: python

    from datetime import datetime

    from runnel import App, Record


    app = App(name="myapp", redis_url="redis://127.0.0.1")


    class Order(Record):
        order_id: int
        created_at: datetime
        amount: float


    orders = app.stream("orders", record=Order, partition_by="order_id")

    await orders.send(Order(order_id=1, created_at=datetime.utcnow(), amount=9.99))

You can also use the command line interface to send events:

.. code-block:: bash

    $ runnel send example:orders "{\"order_id\": 1, \"created_at\": \"2020-07-21T22:09:37Z\" , \"amount\": 99}"

Or in bulk (assuming 'myapp/example.py' includes a stream called 'actions'):

.. code-block:: bash

    $ echo "{\"user_id\": 1, \"type\": \"signup\"}" >> data.jsonl
    $ echo "{\"user_id\": 2, \"type\": \"signup\"}" >> data.jsonl
    $ runnel sendmany myapp.example:actions data.jsonl


Creating a processor
--------------------

Basic
~~~~~

.. code-block:: python

    @app.processor(orders)
    async def printer(events):
        async for order in events.records():
            print(order.amount)


This is where your application logic is implemented. By specifying ``events.records()``
you are requesting that events are automatically deserialized and received as
:attr:`runnel.Record` objects.


Raw events
~~~~~~~~~~

.. code-block:: python

    @app.processor(orders)
    async def printer(events):
        async for order in events:
            print(order.amount)


If you want access to the low-level :attr:`runnel.Event` object, you can omit the
``.records()`` call and iterate over the events directly.


Batching
~~~~~~~~

.. code-block:: python

    @app.processor(orders)
    async def printer(events):
        async for orders in events.take(10, within=2).records():
            assert len(orders) <= 10
            print(orders)


If you want to maximize your processing throughput and your application logic can
support it, you can enable batching of events. ``events.take(10, within=2)`` means take
10 events at a time, but give up after 2 seconds and yield however many are available.
This is intended to support logic which benefits from processing multiple events at
once, e.g. bulk loading records into a database.

.. note::

    Batching of events is separate to prefetching events from Redis. Prefetching of
    multiple events is enabled by default because it greatly benefits efficiency (you
    can control it via the ``prefetch_count`` setting, default=8). Prefetched events are
    buffered inside Runnel workers before they are yielded to your processor. Batching
    controls how those events are yielded: either individually (the default) or as a
    list of n events (using ``events.take(n, within=1)``).

.. warning::

    Runnel acks events after every iteration through the event generator loop. When
    using batching, this means the entire batch will be acked at once. As a result, you
    must process the batch as a single unit atomically. If you iterate over the events
    in a batch one-at-a-time and you fail half-way through, then the entire batch will
    be considered failed (and handled according to your :attr:`runnel.constants.ExceptionPolicy`).
    This will lead to duplicate processing if the batch is retried, or dropped events if
    the batch is ignored.


Background tasks
----------------

You can define background tasks to run at startup using :attr:`runnel.App.task`:

.. code-block:: python

    @app.task
    async def on_startup():
        print("starting")

If you only want to run the task on one worker, set ``on_leader=True``:

.. code-block:: python

    @app.task(on_leader=True)
    async def on_startup():
        print("running once")

Runnel also supports periodic tasks via :attr:`runnel.App.timer` and
:attr:`runnel.App.crontab`:

.. code-block:: python

    @app.timer(interval=10)
    async def every_10_seconds():
        print("10 seconds passed")

.. code-block:: python

    @app.crontab("45 17 * * *")
    async def every_5_45_pm():
        print("It is 5:45pm UTC")

They can also be configured to run only on the lead worker.


Running a worker
----------------

You can run the worker from your shell as follows (assuming you app is defined in
`example.py`):

.. code-block:: bash

    $ runnel worker example:app

For the full set of command line options, see :attr:`runnel.cli.worker`.

By default, the worker will spawn concurrent tasks to run every processor that has been
defined for your app. You can instead select specific processors:

.. code-block:: bash

    $ runnel worker myapp.example:myapp --processors=myproc1,myproc2


Project layout
--------------

Runnel uses decorators to register your processors and background tasks against your app
object. Those decorators must run when your Worker starts up. To ensure this happens,
even if your code is spread across multiple folders, we offer an 'autodiscover' feature:

.. code-block:: python

    from runnel import App

    app = App(
        name="myapp",
        redis_url="redis://127.0.0.1",
        autodiscover="myproj/**/streams.py",  # <-- Specify your glob pattern here.
    )

When set, the worker will search the filesystem using Python's ``pathlib.Path.glob``
function and import any modules that match. In the above example, you could place your
processors in any file named 'streams.py' anywhere in your project.

This feature is disabled by default because specifying the base directory (e.g.
``myproj``) helps make the search efficient. For small projects, you can simply place
your processor code in the same file in which you define your app.


Acknowledgement
---------------

Events are acknowledged at the end of each iteration through the processing loop.

.. code-block:: python

    @app.processor(orders)
    async def printer(events):
        async for order in events.records():
            print(order.amount)
            # This event is acked now by the Runnel system before looping
            # around and yielding a new event.

Since events are acked at the end of the processing block (not at the start), Runnel
guarantees 'at least once' processing: if an event raises an exception midway through
processing and is restarted, that section of processing will run twice.


Exception handling
------------------

Generally speaking, exception handling is harder in systems that make guarantees about
processing order, like Runnel. In a traditional job queue, you can mark jobs as failed
and retry them later, possibly multiple times. If your events must be processed in a
strict order, this option is not available.

Runnel supports three exception policies: halt, quarantine, and ignore (see
:attr:`runnel.constants.ExceptionPolicy`), which can be configured per processor, e.g.

.. code-block:: python

    @app.processor(orders, exception_policy=ExceptionPolicy.HALT)
    async def failer(events):
        async for order in events.records():
            raise ValueError

1. ``ExceptionPolicy.HALT``

Let the exception propagate, halting execution of the affected partition. This is the
default, because it guarantees that your events will not be processed out of order. The
affected partition will be reassigned to another worker, which will likely experience
the same exception and also halt. This will eventually bring down your cluster of
workers. Manual intervention is required: you must fix the offending event and restart
your workers.

2. ``ExceptionPolicy.QUARANTINE``

Mark the affected partition as poisoned, and continue processing all others. This is
similar to halting, but only affects the partition in which a failing event was found.
This option limits the impact of a single bad event, because only one partition will be
stalled. Nonetheless, you must manually intervene by fixing the offending event and
restarting your workers to ensure it is reassigned.

Since this policy will not kill your worker, you must have a notification system in
place to alert you of the need to fix the broken partition. (This is why it's not the
default.)

3. ``ExceptionPolicy.IGNORE``

Suppress the exception and continue processing regardless. This option ensures that your
processors always make forward progress, which is suitable for some use cases (e.g. you
are implementing an approximate counter and it's more important that it's up-to-date
than that it's accurate).

This option can also be coupled with the builtin ``DeadLetterMiddleware``, to forward
failed events to a separate stream, to ensure that no events are lost. See below for an
example:

.. code-block:: python

    from runnel import App, Record, ExceptionPolicy
    from runnel.middleware import DeadLetterMiddleware


    app = App(name="example")


    class Action(Record):
        key: str
        id: int


    actions = app.stream("actions", record=Action, partition_by="key")
    dead_letter = DeadLetterMiddleware(source=actions)


    @app.processor(actions, exception_policy=ExceptionPolicy.IGNORE, middleware=[dead_letter])
    async def proc(events):
        async for event in events.records():
            pass


    @app.processor(dead_letter.sink)
    async def dead(events):
        async for event in events.records():
            pass


Creating middleware
-------------------

The dead-letter feature above is an example of custom middleware. Middleware are objects
with a ``handler`` method, which is an async generator. They are intended to support
sharing common reusable logic between many processors.

The handler methods of a middleware chain form a processing pipeline which runs over
events before they are yielded to the final processor function. Each handler is passed
the previous handler in the pipeline (called 'parent').

.. code-block:: python

    from runnel.interfaces import Middleware

    class Printer(Middleware):
        async def handler(self, parent, **kwargs):
            async for x in parent:
                print(x)
                yield x

    @app.processor(mystream, middleware=[Printer()])
    async def proc(events):
        async for record in events.records():
            pass

.. note::

    Some of Runnel's internal functionality is implemented using middleware. They can be
    found `here <https://github.com/mjwestcott/runnel/tree/master/runnel/middleware>`_.

Since processors can elect to receive a batch of events (see :ref:`Batching`), your
middleware handlers need to support both individual :attr:`runnel.Event` objects and
batches of them:

.. code-block:: python

    from runnel import Event


    class Noop(Middleware):
        async def handler(self, parent, **kwargs):
            async for x in parent:
                assert isinstance(x, (Event, list))
                yield x

Post-processing logic can be added below, in a finally clause. This allows you to
respond to errors further up the chain (e.g. in the final processor code):

.. code-block:: python

    async def handler(self, parent, **kwargs):
        async for x in parent:
            try:
                yield x
            finally:
                await logic()

This is needed because a ``GeneratorExit`` exception will be thrown into the yield point
if an exception is raised in the calling code. (Also note that async generator
finalization is scheduled by the Python runtime asynchronously, but the Runnel framework
ensures it has finished before restarting a processor function.)

If you only want to know if an exception was raised further up the chain, you can use
the following:

.. code-block:: python

    async def handler(self, parent, **kwargs):
        async for x in parent:
            try:
                yield x
            except GeneratorExit:
                await cleanup()
                raise

(Note: Python requires that ``GeneratorExit`` it not ignored, so it must be reraised
here to avoid a ``RuntimeError``)
