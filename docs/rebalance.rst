Rebalance
=========

Runnel workers must coordinate ownership over a set of partitioned Redis stream keys.
This is conducted via a dynamic 'rebalance' algorithm described below.

A single worker
---------------

Let's start with a simple case: a single worker joins an empty group to begin processing
events. Let's assume the stream has 8 partitions.

.. image:: _static/rebalance-1.png

1. Worker 1 announces it has joined the group. It does this by editing the membership
   key in Redis (see :ref:`Redis keys`). Since there are no other workers, it will
   assign itself every partition of the stream. It also adds a message to the control
   stream to notify any other workers that the assignments have changed and they must
   start a rebalance.

2. The membership key is changed in Redis, and a control message is sent to all
   listening workers.

3. Worker 1 receives a message on the control stream saying that it has joined, so it
   performs a rebalance. It attempts to acquire locks in Redis for every partition it
   has been assigned.

4. The partition locks in Redis are now owned by Worker 1 and it can begin processing
   events.

A new worker joins
------------------

Next, another worker joins and must coordinate with the first to split up ownership over
partitions.

.. image:: _static/rebalance-2.png

5. Worker 2 announces it has joined the group. It does this by editing the membership
   key in Redis. Since there is already a worker, it will assign itself partitions 5-8,
   while 1-4 will remain with Worker 1. It also adds a message to the control stream to
   notify any other workers that the assignments have changed and they must start a
   rebalance.

6. The membership key is changes in Redis, and a control message is sent to all
   listening workers.

7. Both workers receive the message on the control stream saying that Worker 2 has
   joined, so they initiate a rebalance.

8. Worker 1 realises that it is no longer assigned partitions 5-8, so it halts
   processing them and releases the corresponding locks in Redis.

9. Partitions 5-8 are no longer owned by anyone. Worker 2 realises that it should
   acquire them.

10. Partitions 5-8 are now owned by Worker 2 and it can begin processing them.

Note that steps 8. and 9. could have happened in reverse. In that case, Worker 2
would have been unable to acquire the locks since Worker 1 would not have released
them yet. Worker 2 would have slept for a small duration before trying again.

Also, note that partitions 1-4 were not affected by the rebalance and Worker 1 did not
have to stop processing them. This greatly benefits processing throughput during
rebalances.

A worker leaves
---------------

Finally, worker 1 leaves the group. Let's say it has received a termination signal. The
worker's internal tasks will be cancelled, but its processors currently processing
events will be given a short grace period to complete (e.g. to finish
:ref:`Acknowledgement`).

.. image:: _static/rebalance-3.png

11. Worker 1 announced it has left the group. It does this by editing the membership key
    in Redis. Since there is one remaining worker, it will assign Worker 2 every
    partition of the stream. It also adds a message to the control stream to notify any
    other workers that the assignments have changed and they must start a rebalance.
    Before exiting, Worker 1 releases its partition locks 1-4.

12. Partitions 1-4 are no longer owned by anyone. The membership key is changes in
    Redis, and a control message is sent to all listening workers.

13. Worker 2 receives the message on the control stream saying that Worker 1 has left, so
    it initiates a rebalance. It realises it must acquire partitions 1-4.

14. Partitions 1-4 are now owned by Worker 2 and it can begin processing them.
