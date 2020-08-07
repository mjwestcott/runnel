Motivation
==========

Whereas traditional job queues do not provide ordering guarantees, Runnel is designed to
process partitions of your event stream strictly in the order events are created.

Ordered event processing
------------------------

Backend services often need to perform background processing. Typically, jobs are placed
on a queue which is processed by multiple workers. The number of workers can be
increased to scale out. In this use case, the architecture is relatively simple because
we pay no attention to the order in which events are processed. Common uses include
sending emails, producing image thumbnails, etc. In Python you might use `Celery
<https://github.com/celery/celery>`_ or `Fennel <https://github.com/mjwestcott/fennel>`_.

Sometimes, however, you care about the order in which events occur. For example, if
events represent rows to be indexed into a search database, it's important that the last
modification is the final one indexed, otherwise searches will return stale data
indefinitely. Similarly, if events represent user actions, processing the second one
('user upgraded account') might rely on the first ('user created account').

Solutions
---------

There are multiple solutions to the problem:

    1. Use one queue for all events, and have one worker process them.

This works, assuming the queue stores events in order, but obviously doesn't scale
because the entire pipeline is processed in serial.

    2. Use one queue per entity, and have at most one worker per queue.

The ordering requirement can usually be constrained to an entity. In the user actions
example above, events for each user must be processed in-order, but the absolute
ordering between all users wasn't important. In that case, we can solve the scale
problem by introducing parallelism at the queue level. If queues and workers are cheap
to operate, or there are a small number of distinct entities, this would be feasible.

    3. Use a fixed number of queues, partition events by entity, and have at most one worker
    per queue.

In practice, we may need to support a large number of entities (e.g. millions of users)
and queues are not trivial to create, so this third option is sensible. Our degree of
parallelism is controlled by the number of queues we choose to create. Events must have
an entity id which is used to select the right queue to which it should be sent.

We have essentially described the architecture of large-scale event processing pipelines
popularised by `Kafka <https://kafka.apache.org/>`_ and its `ecosystem
<https://kafka.apache.org/documentation/streams/>`_. AWS SQS also supports `partitioned,
ordered queues <https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/FIFO-queues.html>`_.
So why do we need another solution? Unlike the alternatives, Redis is free, open-source,
and, crucially, simple and easy to operate. The question is: does it support our use case?

Redis Streams
-------------

Starting in version 5.0, Redis offers a `'stream' <https://redis.io/topics/streams-intro>`_
data structure. You might expect it to solve our use case directly, especially since it
provides a 'consumer group' abstraction inspired by Kafka.

However, the builtin streams commands were designed to support a slightly different
scenario. The 'consumer group' abstraction allows multiple consumers to share
responsibility for processing a single stream. This is akin to the traditional job queue
described above: it loses the ordering guarantee that we care about.

There is no builtin support for partitioning a stream or coordinating multiple workers
across those partitions (e.g. a rebalance algorithm for assigning ownership of
partitions to workers `as found in Kafka <https://medium.com/streamthoughts/apache-kafka-rebalance-protocol-or-the-magic-behind-your-streams-applications-e94baf68e4f2>`_).

So if we are going to use Redis as an ordered, partitioned, event processing backend, we
need to build the necessary features in a client library on top. For a detailed
breakdown of how Runnel solves these problems, see the :ref:`Architecture` section.
