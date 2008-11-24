.. _usage:

=====
Usage
=====

Overview and Basics
===================

The basic usage of zc.async does not depend on a particular configuration
of the back-end mechanism for getting the jobs done.  Moreover, on some
teams, it will be the responsibility of one person or group to configure
zc.async, but a service available to the code of all team members.  Therefore,
we begin our detailed discussion with regular usage, assuming configuration
has already happened.  Subsequent sections discuss configuring zc.async
with and without Zope 3.

So, let's assume we have a queue with dispatchers, reactors and agents all
waiting to fulfill jobs placed into the queue.  We start with a connection
object, ``conn``, and some convenience functions introduced along the way that
help us simulate time passing and work being done [#usageSetUp]_.

-------------------
Obtaining the queue
-------------------

First, how do we get the queue?  Your installation may have some
conveniences.  For instance, the Zope 3 configuration described below
makes it possible to get the primary queue with an adaptation call like
``zc.async.interfaces.IQueue(a_persistent_object_with_db_connection)``.

But failing that, queues are always expected to be in a zc.async.queue.Queues
mapping found off the ZODB root in a key defined by the constant
zc.async.interfaces.KEY.

    >>> import zc.async.interfaces
    >>> zc.async.interfaces.KEY
    'zc.async'
    >>> root = conn.root()
    >>> queues = root[zc.async.interfaces.KEY]
    >>> import zc.async.queue
    >>> isinstance(queues, zc.async.queue.Queues)
    True

As the name implies, ``queues`` is a collection of queues. As discussed later,
it's possible to have multiple queues, as a tool to distribute and control
work. We will assume a convention of a queue being available in the '' (empty
string).

    >>> queues.keys()
    ['']
    >>> queue = queues['']

-------------
``queue.put``
-------------

Now we want to actually get some work done.  The simplest case is simple
to perform: pass a persistable callable to the queue's ``put`` method and
commit the transaction.

    >>> def send_message():
    ...     print "imagine this sent a message to another machine"
    >>> job = queue.put(send_message)
    >>> import transaction
    >>> transaction.commit()

Note that this won't really work in an interactive session: the callable needs
to be picklable, as discussed above, so ``send_message`` would need to be
a module global, for instance.

The ``put`` returned a job.  Now we need to wait for the job to be
performed.  We would normally do this by really waiting.  For our
examples, we will use a helper method on the testing reactor to ``wait_for``
the job to be completed.

    >>> reactor.wait_for(job)
    imagine this sent a message to another machine

We also could have used the method of a persistent object.  Here's another
quick example.

First we define a simple persistent.Persistent subclass and put an instance of
it in the database [#commit_for_multidatabase]_.

    >>> import persistent
    >>> class Demo(persistent.Persistent):
    ...     counter = 0
    ...     def increase(self, value=1):
    ...         self.counter += value
    ...
    >>> root['demo'] = Demo()
    >>> transaction.commit()

Now we can put the ``demo.increase`` method in the queue.

    >>> root['demo'].counter
    0
    >>> job = queue.put(root['demo'].increase)
    >>> transaction.commit()

    >>> reactor.wait_for(job)
    >>> root['demo'].counter
    1

The method was called, and the persistent object modified!

To reiterate, only pickleable callables such as global functions and the
methods of persistent objects can be used. This rules out, for instance,
lambdas and other functions created dynamically. As we'll see below, the job
instance can help us out there somewhat by offering closure-like features.

-----------------------------------
``queue.pull`` and ``queue.remove``
-----------------------------------

If you put a job into a queue and it hasn't been claimed yet and you want to
cancel the job, ``pull`` or ``remove`` it from the queue.

The ``pull`` method removes the first job, or takes an integer index.

    >>> len(queue)
    0
    >>> job1 = queue.put(send_message)
    >>> job2 = queue.put(send_message)
    >>> len(queue)
    2
    >>> job1 is queue.pull()
    True
    >>> list(queue) == [job2]
    True
    >>> job1 is queue.put(job1)
    True
    >>> list(queue) == [job2, job1]
    True
    >>> job1 is queue.pull(-1)
    True
    >>> job2 is queue.pull()
    True
    >>> len(queue)
    0

The ``remove`` method removes the specific given job.

    >>> job1 = queue.put(send_message)
    >>> job2 = queue.put(send_message)
    >>> len(queue)
    2
    >>> queue.remove(job1)
    >>> list(queue) == [job2]
    True
    >>> job1 is queue.put(job1)
    True
    >>> list(queue) == [job2, job1]
    True
    >>> queue.remove(job1)
    >>> list(queue) == [job2]
    True
    >>> queue.remove(job2)
    >>> len(queue)
    0

---------------
Scheduled Calls
---------------

When using ``put``, you can also pass a datetime.datetime to schedule a call. A
datetime without a timezone is considered to be in the UTC timezone.

    >>> t = transaction.begin()
    >>> import datetime
    >>> import pytz
    >>> datetime.datetime.now(pytz.UTC)
    datetime.datetime(2006, 8, 10, 15, 44, 33, 211, tzinfo=<UTC>)
    >>> job = queue.put(
    ...     send_message, begin_after=datetime.datetime(
    ...         2006, 8, 10, 15, 56, tzinfo=pytz.UTC))
    >>> job.begin_after
    datetime.datetime(2006, 8, 10, 15, 56, tzinfo=<UTC>)
    >>> transaction.commit()
    >>> reactor.wait_for(job, attempts=2) # +5 virtual seconds
    TIME OUT
    >>> reactor.wait_for(job, attempts=2) # +5 virtual seconds
    TIME OUT
    >>> datetime.datetime.now(pytz.UTC)
    datetime.datetime(2006, 8, 10, 15, 44, 43, 211, tzinfo=<UTC>)

    >>> zc.async.testing.set_now(datetime.datetime(
    ...     2006, 8, 10, 15, 56, tzinfo=pytz.UTC))
    >>> reactor.wait_for(job)
    imagine this sent a message to another machine
    >>> datetime.datetime.now(pytz.UTC) >= job.begin_after
    True

If you set a time that has already passed, it will be run as if it had
been set to run as soon as possible [#already_passed]_...unless the job
has already timed out, in which case the job fails with an
abort [#already_passed_timed_out]_.

The queue's ``put`` method is the essential API. ``pull`` is used rarely. Other
methods are used to introspect, but are not needed for basic usage.

But what is that result of the ``put`` call in the examples above?  A
job?  What do you do with that?

Jobs
====

--------
Overview
--------

The result of a call to ``put`` returns an ``IJob``. The job represents the
pending result. This object has a lot of functionality that's explored in other
documents in this package, and demonstrated a bit below, but here's a summary.

- You can introspect, and even modify, the call and its arguments.

- You can specify that the job should be run serially with others of a given
  identifier.

- You can specify other calls that should be made on the basis of the result of
  this call.

- You can persist a reference to it, and periodically (after syncing your
  connection with the database, which happens whenever you begin or commit a
  transaction) check its ``status`` to see if it is equal to
  ``zc.async.interfaces.COMPLETED``. When it is, the call has run to completion,
  either to success or an exception.

- You can look at the result of the call (once ``COMPLETED``). It might be the
  result you expect, or a ``zc.twist.Failure``, a subclass of
  ``twisted.python.failure.Failure``, which is a way to safely communicate
  exceptions across connections and machines and processes.

-------
Results
-------

So here's a simple story.  What if you want to get a result back from a
call?  Look at the job.result after the call is ``COMPLETED``.

    >>> def imaginaryNetworkCall():
    ...     # let's imagine this makes a network call...
    ...     return "200 OK"
    ...
    >>> job = queue.put(imaginaryNetworkCall)
    >>> print job.result
    None
    >>> job.status == zc.async.interfaces.PENDING
    True
    >>> transaction.commit()
    >>> reactor.wait_for(job)
    >>> t = transaction.begin()
    >>> job.result
    '200 OK'
    >>> job.status == zc.async.interfaces.COMPLETED
    True

--------
Closures
--------

What's more, you can pass a Job to the ``put`` call.  This means that you
aren't constrained to simply having simple non-argument calls performed
asynchronously, but you can pass a job with a call, arguments, and
keyword arguments--effectively, a kind of closure.  Here's a quick example.
We'll use the demo object, and its increase method, that we introduced
above, but this time we'll include some arguments [#job]_.

With positional arguments:

    >>> t = transaction.begin()
    >>> job = queue.put(
    ...     zc.async.job.Job(root['demo'].increase, 5))
    >>> transaction.commit()
    >>> reactor.wait_for(job)
    >>> t = transaction.begin()
    >>> root['demo'].counter
    6

With keyword arguments (``value``):

    >>> job = queue.put(
    ...     zc.async.job.Job(root['demo'].increase, value=10))
    >>> transaction.commit()
    >>> reactor.wait_for(job)
    >>> t = transaction.begin()
    >>> root['demo'].counter
    16

Note that arguments to these jobs can be any persistable object.

--------
Failures
--------

What happens if a call raises an exception?  The return value is a Failure.

    >>> def I_am_a_bad_bad_function():
    ...     return foo + bar
    ...
    >>> job = queue.put(I_am_a_bad_bad_function)
    >>> transaction.commit()
    >>> reactor.wait_for(job)
    >>> t = transaction.begin()
    >>> job.result # doctest: +ELLIPSIS +NORMALIZE_WHITESPACE
    <zc.twist.Failure ...exceptions.NameError...

Failures can provide useful information such as tracebacks.

    >>> print job.result.getTraceback()
    ... # doctest: +ELLIPSIS +NORMALIZE_WHITESPACE
    Traceback (most recent call last):
    ...
    exceptions.NameError: global name 'foo' is not defined
    <BLANKLINE>

---------
Callbacks
---------

You can register callbacks to handle the result of a job, whether a
Failure or another result.

Note that, unlike callbacks on a Twisted deferred, these callbacks do not
change the result of the original job. Since callbacks are jobs, you can chain
results, but generally callbacks for the same job all get the same result as
input.

Also note that, during execution of a callback, there is no guarantee that
the callback will be processed on the same machine as the main call.  Also,
some of the ``local`` functions, discussed below, will not work as desired.

Here's a simple example of reacting to a success.

    >>> def I_scribble_on_strings(string):
    ...     return string + ": SCRIBBLED"
    ...
    >>> job = queue.put(imaginaryNetworkCall)
    >>> callback = job.addCallback(I_scribble_on_strings)
    >>> transaction.commit()
    >>> reactor.wait_for(job)
    >>> job.result
    '200 OK'
    >>> callback.result
    '200 OK: SCRIBBLED'

Here's a more complex example of handling a Failure, and then chaining
a subsequent callback.

    >>> def I_handle_NameErrors(failure):
    ...     failure.trap(NameError) # see twisted.python.failure.Failure docs
    ...     return 'I handled a name error'
    ...
    >>> job = queue.put(I_am_a_bad_bad_function)
    >>> callback1 = job.addCallbacks(failure=I_handle_NameErrors)
    >>> callback2 = callback1.addCallback(I_scribble_on_strings)
    >>> transaction.commit()
    >>> reactor.wait_for(job)
    >>> job.result  # doctest: +ELLIPSIS +NORMALIZE_WHITESPACE
    <zc.twist.Failure ...exceptions.NameError...
    >>> callback1.result
    'I handled a name error'
    >>> callback2.result
    'I handled a name error: SCRIBBLED'

Advanced Techniques and Tools
=============================

**Important**

The job and its functionality described above are the core zc.async tools.

The following are advanced techniques and tools of various complexities. You
can use zc.async very productively without ever understanding or using them. If
the following do not make sense to you now, please just move on for now.

--------------
zc.async.local
--------------

Jobs always run their callables in a thread, within the context of a
connection to the ZODB. The callables have access to five special
thread-local functions if they need them for special uses.  These are
available off of zc.async.local.

``zc.async.local.getJob()``
    The ``getJob`` function can be used to examine the job, to get
    a connection off of ``_p_jar``, to get the queue into which the job
    was put, or other uses.

``zc.async.local.getQueue()``
    The ``getQueue`` function can be used to examine the queue, to put another
    task into the queue, or other uses. It is sugar for
    ``zc.async.local.getJob().queue``.

``zc.async.local.setLiveAnnotation(name, value, job=None)``
    The ``setLiveAnnotation`` tells the agent to set an annotation on a job,
    by default the current job, *in another connection*.  This makes it
    possible to send messages about progress or for coordination while in the
    middle of other work.

    As a simple rule, only send immutable objects like strings or
    numbers as values [#setLiveAnnotation]_.

``zc.async.local.getLiveAnnotation(name, default=None, timeout=0, poll=1, job=None)``
    The ``getLiveAnnotation`` tells the agent to get an annotation for a job,
    by default the current job, *from another connection*.  This makes it
    possible to send messages about progress or for coordination while in the
    middle of other work.

    As a simple rule, only ask for annotation values that will be
    immutable objects like strings or numbers [#getLiveAnnotation]_.

    If the ``timeout`` argument is set to a positive float or int, the function
    will wait at least that number of seconds until an annotation of the
    given name is available. Otherwise, it will return the ``default`` if the
    name is not present in the annotations. The ``poll`` argument specifies
    approximately how often to poll for the annotation, in seconds (to be more
    precise, a subsequent poll will be min(poll, remaining seconds until
    timeout) seconds away).

``zc.async.local.getReactor()``
    The ``getReactor`` function returns the job's dispatcher's reactor.  The
    ``getLiveAnnotation`` and ``setLiveAnnotation`` functions use this,
    along with the zc.twist package, to work their magic; if you are feeling
    adventurous, you can do the same.

``zc.async.local.getDispatcher()``
    The ``getDispatcher`` function returns the job's dispatcher.  This might
    be used to analyze its non-persistent poll data structure, for instance
    (described later in configuration discussions).

Let's give three of those a whirl. We will write a function that examines the
job's state while it is being called, and sets the state in an annotation, then
waits for our flag to finish.

    >>> def annotateStatus():
    ...     zc.async.local.setLiveAnnotation(
    ...         'zc.async.test.status',
    ...         zc.async.local.getJob().status)
    ...     zc.async.local.getLiveAnnotation(
    ...         'zc.async.test.flag', timeout=5)
    ...     return 42
    ...
    >>> job = queue.put(annotateStatus)
    >>> transaction.commit()
    >>> import time
    >>> def wait_for_annotation(job, key):
    ...     reactor.time_flies(dispatcher.poll_interval) # starts thread
    ...     for i in range(10):
    ...         while reactor.time_passes():
    ...             pass
    ...         transaction.begin()
    ...         if key in job.annotations:
    ...             break
    ...         time.sleep(0.1)
    ...     else:
    ...         print 'Timed out' + repr(dict(job.annotations))
    ...
    >>> wait_for_annotation(job, 'zc.async.test.status')
    >>> job.annotations['zc.async.test.status'] == (
    ...     zc.async.interfaces.ACTIVE)
    True
    >>> job.status == zc.async.interfaces.ACTIVE
    True

[#stats_1]_

    >>> job.annotations['zc.async.test.flag'] = True
    >>> transaction.commit()
    >>> reactor.wait_for(job)
    >>> job.result
    42

[#stats_2]_ ``getReactor`` and ``getDispatcher`` are for advanced use
cases and are not explored further here.

----------
Job Quotas
----------

One class of asynchronous jobs are ideally serialized.  For instance,
you may want to reduce or eliminate the chance of conflict errors when
updating a text index.  One way to do this kind of serialization is to
use the ``quota_names`` attribute of the job.

For example, let's first show two non-serialized jobs running at the
same time, and then two serialized jobs created at the same time.
The first part of the example does not use queue_names, to show a contrast.

For our parallel jobs, we'll do something that would create a deadlock
if they were serial.  Notice that we are mutating the job arguments after
creation to accomplish this, which is supported.

    >>> def waitForParallel(other):
    ...     zc.async.local.setLiveAnnotation(
    ...         'zc.async.test.flag', True)
    ...     zc.async.local.getLiveAnnotation(
    ...         'zc.async.test.flag', job=other, timeout=0.4, poll=0)
    ...
    >>> job1 = queue.put(waitForParallel)
    >>> job2 = queue.put(waitForParallel)
    >>> job1.args.append(job2)
    >>> job2.args.append(job1)
    >>> transaction.commit()
    >>> reactor.wait_for(job1, job2)
    >>> job1.status == zc.async.interfaces.COMPLETED
    True
    >>> job2.status == zc.async.interfaces.COMPLETED
    True
    >>> job1.result is job2.result is None
    True

On the other hand, for our serial jobs, we'll do something that would fail
if it were parallel.  We'll rely on ``quota_names``.

Quotas verge on configuration, which is not what this section is about,
because they must be configured on the queue.  However, they also affect
usage, so we show them here.

    >>> def pause(other):
    ...     zc.async.local.setLiveAnnotation(
    ...         'zc.async.test.flag', True)
    ...     res = zc.async.local.getLiveAnnotation(
    ...         'zc.async.test.flag', timeout=0.4, poll=0.1, job=other)
    ...
    >>> job1 = queue.put(pause)
    >>> job2 = queue.put(imaginaryNetworkCall)

You can't put a name in ``quota_names`` unless the quota has been created
in the queue.

    >>> job1.quota_names = ('test',)
    Traceback (most recent call last):
    ...
    ValueError: ('unknown quota name', 'test')
    >>> queue.quotas.create('test')
    >>> job1.quota_names = ('test',)
    >>> job2.quota_names = ('test',)

Now we can see the two jobs being performed serially.

    >>> job1.args.append(job2)
    >>> transaction.commit()
    >>> reactor.time_flies(dispatcher.poll_interval)
    1
    >>> for i in range(10):
    ...     t = transaction.begin()
    ...     if job1.status == zc.async.interfaces.ACTIVE:
    ...         break
    ...     time.sleep(0.1)
    ... else:
    ...     print 'TIME OUT'
    ...
    >>> job2.status == zc.async.interfaces.PENDING
    True
    >>> job2.annotations['zc.async.test.flag'] = False
    >>> transaction.commit()
    >>> reactor.wait_for(job1)
    >>> reactor.wait_for(job2)
    >>> print job1.result
    None
    >>> print job2.result
    200 OK

Quotas can be configured for limits greater than one at a time, if desired.
This may be valuable when a needed resource is only available in limited
numbers at a time.

Note that, while quotas are valuable tools for doing serialized work such as
updating a text index, other optimization features sometimes useful for this
sort of task, such as collapsing similar jobs, are not provided directly by
this package. This functionality could be trivially built on top of zc.async,
however [#idea_for_collapsing_jobs]_.

--------------
Returning Jobs
--------------

Our examples so far have done work directly.  What if the job wants to
orchestrate other work?  One way this can be done is to return another
job.  The result of the inner job will be the result of the first
job once the inner job is finished.  This approach can be used to
break up the work of long running processes; to be more cooperative to
other jobs; and to make parts of a job that can be parallelized available
to more workers.

Serialized Work
---------------

First, consider a serialized example.  This simple pattern is one approach.

    >>> def second_job(value):
    ...     # imagine a lot of work goes on...
    ...     return value * 2
    ...
    >>> def first_job():
    ...     # imagine a lot of work goes on...
    ...     intermediate_value = 21
    ...     queue = zc.async.local.getJob().queue
    ...     return queue.put(zc.async.job.Job(
    ...         second_job, intermediate_value))
    ...
    >>> job = queue.put(first_job)
    >>> transaction.commit()
    >>> reactor.wait_for(job, attempts=3)
    TIME OUT
    >>> len(agent)
    1
    >>> reactor.wait_for(job, attempts=3)
    >>> job.result
    42

The job is now out of the agent.

    >>> len(agent)
    0

The second_job could also have returned a job, allowing for additional
legs.  Once the last job returns a real result, it will cascade through the
past jobs back up to the original one.

A different approach could have used callbacks.  Using callbacks can be
somewhat more complicated to follow, but can allow for a cleaner
separation of code: dividing code that does work from code that orchestrates
the jobs. The ``serial`` helper function in the job module uses this pattern.
Here's a quick example of the helper function [#define_longer_wait]_.

    >>> def job_zero():
    ...     return 0
    ...
    >>> def job_one():
    ...     return 1
    ...
    >>> def job_two():
    ...     return 2
    ...
    >>> def postprocess(zero, one, two):
    ...     return zero.result, one.result, two.result
    ...
    >>> job = queue.put(zc.async.job.serial(job_zero, job_one, job_two,
    ...                                     postprocess=postprocess))
    >>> transaction.commit()

    >>> wait_repeatedly()
    ... # doctest: +ELLIPSIS
    TIME OUT...

    >>> job.result
    (0, 1, 2)

[#extra_serial_tricks]_

The ``parallel`` example we use below follows a similar pattern.

Parallelized Work
-----------------

Now how can we set up parallel jobs?  There are other good ways, but we
can describe one way that avoids potential problems with the
current-as-of-this-writing (ZODB 3.8 and trunk) default optimistic MVCC
serialization behavior in the ZODB.  The solution uses callbacks, which
also allows us to cleanly divide the "work" code from the synchronization
code, as described in the previous paragraph.

First, we'll define the jobs that do work.  ``job_A``, ``job_B``, and
``job_C`` will be jobs that can be done in parallel, and
``postprocess`` will be a function that assembles the job results for a
final result.

    >>> def job_A():
    ...     # imaginary work...
    ...     return 7
    ...
    >>> def job_B():
    ...     # imaginary work...
    ...     return 14
    ...
    >>> def job_C():
    ...     # imaginary work...
    ...     return 21
    ...
    >>> def postprocess(*jobs):
    ...     # this callable represents one that needs to wait for the
    ...     # parallel jobs to be done before it can process them and return
    ...     # the final result
    ...     return sum(job.result for job in jobs)
    ...

This can be handled by a convenience function, ``parallel``, that will arrange
everything for you.

    >>> job = queue.put(zc.async.job.parallel(
    ...     job_A, job_B, job_C, postprocess=postprocess))
    >>> transaction.commit()

Now we just wait for the result.

    >>> wait_repeatedly()
    ... # doctest: +ELLIPSIS
    TIME OUT...

    >>> job.result
    42

Ta-da! [#extra_parallel_tricks]_

Now, how did this work?  Let's look at a simple implementation directly.  We'll
use a slightly different postprocess, that expects results directly rather than
the jobs.

    >>> def postprocess(*results):
    ...     # this callable represents one that needs to wait for the
    ...     # parallel jobs to be done before it can process them and return
    ...     # the final result
    ...     return sum(results)
    ...

This code works with jobs to get everything done. Note, in the callback
function, that mutating the same object we are checking (job.args) is the way
we are enforcing necessary serializability with MVCC turned on.

    >>> def callback(job, result):
    ...     job.args.append(result)
    ...     if len(job.args) == 3: # all results are in
    ...         zc.async.local.getJob().queue.put(job)
    ...
    >>> def main_job():
    ...     job = zc.async.job.Job(postprocess)
    ...     queue = zc.async.local.getJob().queue
    ...     for j in (job_A, job_B, job_C):
    ...         queue.put(j).addCallback(
    ...             zc.async.job.Job(callback, job))
    ...     return job
    ...

That may be a bit mind-blowing at first.  The trick to catch here is that,
because the main_job returns a job, the result of that job will become the
result of the main_job once the returned (``post_process``) job is done.

Now we'll put this in and let it cook.

    >>> job = queue.put(main_job)
    >>> transaction.commit()

    >>> wait_repeatedly()
    ... # doctest: +ELLIPSIS
    TIME OUT...
    >>> job.result
    42

Once again, ta-da!

For real-world usage, you'd also probably want to deal with the possibility of
one or more of the jobs generating a Failure, among other edge cases.  The
``parallel`` function introduced above helps you handle this by returning
jobs, rather than results, so you can analyze what went wrong and try to handle
it.

-------------------
Returning Deferreds
-------------------

What if you want to do work that doesn't require a ZODB connection?  You
can also return a Twisted deferred (twisted.internet.defer.Deferred).
When you then ``callback`` the deferred with the eventual result, the
agent will be responsible for setting that value on the original
deferred and calling its callbacks.  This can be a useful trick for
making network calls using Twisted or zc.ngi, for instance.

    >>> def imaginaryNetworkCall2(deferred):
    ...     # make a network call...
    ...     deferred.callback('200 OK')
    ...
    >>> import twisted.internet.defer
    >>> import threading
    >>> def delegator():
    ...     deferred = twisted.internet.defer.Deferred()
    ...     t = threading.Thread(
    ...         target=imaginaryNetworkCall2, args=(deferred,))
    ...     t.run()
    ...     return deferred
    ...
    >>> job = queue.put(delegator)
    >>> transaction.commit()
    >>> reactor.wait_for(job)
    >>> job.result
    '200 OK'

Conclusion
==========

This concludes our discussion of zc.async usage. The :ref:`next section
<configuration-without-zope-3>` shows how to configure zc.async without
Zope 3 [#stop_usage_reactor]_.

.. _`next section`: :ref:`configuration-without-zope-3`

.. rubric:: Footnotes

.. [#usageSetUp] We set up the configuration for our usage examples here.

    You must have two adapter registrations: IConnection to
    ITransactionManager, and IPersistent to IConnection.  We will also
    register IPersistent to ITransactionManager because the adapter is
    designed for it.

    We also need to be able to get data manager partials for functions and
    methods; normal partials for functions and methods; and a data manager for
    a partial. Here are the necessary registrations.

    The dispatcher will look for a UUID utility, so we also need one of these.

    The ``zc.async.configure.base`` function performs all of these
    registrations. If you are working with zc.async without ZCML you might want
    to use it or ``zc.async.configure.minimal`` as a convenience.

    >>> import zc.async.configure
    >>> zc.async.configure.base()

    Now we'll set up the database, and make some policy decisions.  As
    the subsequent ``configuration`` sections discuss, some helpers are
    available for you to set this up if you'd like, though it's not too
    onerous to do it by hand.

    We'll use a test reactor that we can control.

    >>> import zc.async.testing
    >>> reactor = zc.async.testing.Reactor()
    >>> reactor.start() # this monkeypatches datetime.datetime.now

    We need to instantiate the dispatcher with a reactor and a DB.  We
    have the reactor, so here is the DB.  We use a FileStorage rather
    than a MappingStorage variant typical in tests and examples because
    we want MVCC.

    >>> import ZODB.FileStorage
    >>> storage = ZODB.FileStorage.FileStorage(
    ...     'zc_async.fs', create=True)
    >>> from ZODB.DB import DB
    >>> db = DB(storage)
    >>> conn = db.open()
    >>> root = conn.root()

    Now let's create the mapping of queues, and a single queue.

    >>> import zc.async.queue
    >>> import zc.async.interfaces
    >>> mapping = root[zc.async.interfaces.KEY] = zc.async.queue.Queues()
    >>> queue = mapping[''] = zc.async.queue.Queue()
    >>> import transaction
    >>> transaction.commit()

    Now we can instantiate, activate, and perform some reactor work in order
    to let the dispatcher register with the queue.

    >>> import zc.async.dispatcher
    >>> dispatcher = zc.async.dispatcher.Dispatcher(db, reactor)
    >>> dispatcher.activate()
    >>> reactor.time_flies(1)
    1

    The UUID is set on the dispatcher.

    >>> import zope.component
    >>> import zc.async.interfaces
    >>> UUID = zope.component.getUtility(zc.async.interfaces.IUUID)
    >>> dispatcher.UUID == UUID
    True

    Here's an agent named 'main'

    >>> import zc.async.agent
    >>> agent = zc.async.agent.Agent()
    >>> queue.dispatchers[dispatcher.UUID]['main'] = agent
    >>> agent.filter is None
    True
    >>> agent.size
    3
    >>> transaction.commit()

.. [#commit_for_multidatabase] We commit before we do the next step as a
    good practice, in case the queue is from a different database than
    the root.  See the configuration sections for a discussion about
    why putting the queue in another database might be a good idea.

    Rather than committing the transaction,
    ``root._p_jar.add(root['demo'])`` would also accomplish the same
    thing from a multi-database perspective, without a commit.  It was
    not used in the example because the author judged the
    ``transaction.commit()`` to be less jarring to the reader.  If you
    are down here reading this footnote, maybe the author was wrong. :-)

.. [#already_passed]

    >>> t = transaction.begin()
    >>> job = queue.put(
    ...     send_message, datetime.datetime(2006, 8, 10, 15, tzinfo=pytz.UTC))
    >>> transaction.commit()
    >>> reactor.wait_for(job)
    imagine this sent a message to another machine

    It's worth noting that this situation constitutes a small exception
    in the handling of scheduled calls.  Scheduled calls usually get
    preference when jobs are handed out over normal non-scheduled "as soon as
    possible" jobs.  However, setting the begin_after date to an earlier
    time puts the job at the end of the (usually) FIFO queue of non-scheduled
    tasks: it is treated exactly as if the date had not been specified.

.. [#already_passed_timed_out]

    >>> t = transaction.begin()
    >>> job = queue.put(
    ...     send_message, datetime.datetime(2006, 7, 21, 12, tzinfo=pytz.UTC),
    ...     datetime.timedelta(hours=1))
    >>> transaction.commit()
    >>> reactor.wait_for(job)
    >>> job.result # doctest: +ELLIPSIS
    <zc.twist.Failure ...zc.async.interfaces.TimeoutError...
    >>> import sys
    >>> job.result.printTraceback(sys.stdout) # doctest: +NORMALIZE_WHITESPACE
    Traceback (most recent call last):
    Failure: zc.async.interfaces.TimeoutError:

.. [#job] The Job class can take arguments and keyword arguments
    for the wrapped callable at call time as well, similar to Python
    2.5's `partial`.  This will be important when we use the Job as
    a callback.  For this use case, though, realize that the job
    will be called with no arguments, so you must supply all necessary
    arguments for the callable at creation time.

.. [#setLiveAnnotation]  Here's the real rule, which is more complex.
    *Do not send non-persistent mutables or a persistent.Persistent
    object without a connection, unless you do not refer to it again in
    the current job.*

.. [#getLiveAnnotation] Here's the real rule. *To prevent surprising
    errors, do not request an annotation that might be a persistent
    object.*

.. [#stats_1] The dispatcher has a getStatistics method.  It also shows the
    fact that there is an active task.

    >>> import pprint
    >>> pprint.pprint(dispatcher.getStatistics()) # doctest: +ELLIPSIS
    {'failed': 2,
     'longest active': (..., 'unnamed'),
     'longest failed': (..., 'unnamed'),
     'longest successful': (..., 'unnamed'),
     'shortest active': (..., 'unnamed'),
     'shortest failed': (..., 'unnamed'),
     'shortest successful': (..., 'unnamed'),
     'started': 12,
     'statistics end': datetime.datetime(2006, 8, 10, 15, 44, 22, 211),
     'statistics start': datetime.datetime(2006, 8, 10, 15, 56, 47, 211),
     'successful': 9,
     'unknown': 0}

    We can also see the active job with ``getActiveJobIds``

    >>> job_ids = dispatcher.getActiveJobIds()
    >>> len(job_ids)
    1
    >>> info = dispatcher.getJobInfo(*job_ids[0])
    >>> pprint.pprint(info) # doctest: +ELLIPSIS
    {'agent': 'main',
     'call': "<zc.async.job.Job (oid ..., db 'unnamed') ``zc.async.doctest_test.annotateStatus()``>",
     'completed': None,
     'failed': False,
     'poll id': ...,
     'queue': '',
     'quota names': (),
     'reassigned': False,
     'result': None,
     'started': datetime.datetime(...),
     'thread': ...}
     >>> info['thread'] is not None
     True
     >>> info['poll id'] is not None
     True


.. [#stats_2] Now the task is done, as the stats reflect.

    >>> pprint.pprint(dispatcher.getStatistics()) # doctest: +ELLIPSIS
    {'failed': 2,
     'longest active': None,
     'longest failed': (..., 'unnamed'),
     'longest successful': (..., 'unnamed'),
     'shortest active': None,
     'shortest failed': (..., 'unnamed'),
     'shortest successful': (..., 'unnamed'),
     'started': 12,
     'statistics end': datetime.datetime(2006, 8, 10, 15, 44, 22, 211),
     'statistics start': datetime.datetime(2006, 8, 10, 15, 56, 52, 211),
     'successful': 10,
     'unknown': 0}

    Note that these statistics eventually rotate out. By default, poll info
    will eventually rotate out after about 30 minutes (400 polls), and job info
    will only keep the most recent 200 stats in-memory. To look in history
    beyond these limits, check your logs.

    The ``getActiveJobIds`` list is empty now.

    >>> dispatcher.getActiveJobIds()
    []
    >>> info = dispatcher.getJobInfo(*job_ids[0])
    >>> pprint.pprint(info) # doctest: +ELLIPSIS
    {'agent': 'main',
     'call': "<zc.async.job.Job (oid ..., db 'unnamed') ``zc.async.doctest_test.annotateStatus()``>",
     'completed': datetime.datetime(...),
     'failed': False,
     'poll id': ...,
     'queue': '',
     'quota names': (),
     'reassigned': False,
     'result': '42',
     'started': datetime.datetime(...),
     'thread': ...}

     >>> info['thread'] is not None
     True
     >>> info['poll id'] is not None
     True

.. [#idea_for_collapsing_jobs] For instance, here is one approach.  Imagine
    you are queueing the job of indexing documents. If the same document has a
    request to index, the job could simply walk the queue and remove (``pull``)
    similar tasks, perhaps aggregating any necessary data. Since the jobs are
    serial because of a quota, no other worker should be trying to work on
    those jobs.

    Alternatively, you could use a standalone, non-zc.async queue of things to
    do, and have the zc.async job just pull from that queue.  You might use
    zc.queue for this stand-alone queue, or zc.catalogqueue.

.. [#define_longer_wait]
    >>> def wait_repeatedly():
    ...     for i in range(10):
    ...         reactor.wait_for(job, attempts=3)
    ...         if job.status == zc.async.interfaces.COMPLETED:
    ...             break
    ...     else:
    ...         assert False, 'never completed'
    ...

.. [#extra_serial_tricks] The ``serial`` helper can accept a partial closure
    for a ``postprocess`` argument.

    >>> def postprocess(extra_info, *jobs):
    ...     return extra_info, tuple(j.result for j in jobs)
    ...
    >>> job = queue.put(zc.async.job.serial(
    ...     job_zero, job_one, job_two,
    ...     postprocess=zc.async.job.Job(postprocess, 'foo')))
    >>> transaction.commit()

    >>> wait_repeatedly()
    ... # doctest: +ELLIPSIS
    TIME OUT...

    >>> job.result
    ('foo', (0, 1, 2))

    The list of jobs can be extended by adding them to the args of the job
    returned by ``serial`` under these circumstances:

    - before the job has started,

    - by an inner job while it is running, or

    - by any callback added to any inner job *before* that inner job has begun.

    Here's an example.

    >>> def postprocess(*jobs):
    ...     return [j.result for j in jobs]
    ...
    >>> job = queue.put(zc.async.job.serial(postprocess=postprocess))
    >>> def second_job():
    ...     return 'second'
    ...
    >>> def third_job():
    ...     return 'third'
    ...
    >>> def schedule_third(main_job, ignored):
    ...     main_job.args.append(zc.async.job.Job(third_job))
    ...
    >>> def first_job(main_job):
    ...     j = zc.async.job.Job(second_job)
    ...     main_job.args.append(j)
    ...     j.addCallback(zc.async.job.Job(schedule_third, main_job))
    ...     return 'first'
    ...
    >>> job.args.append(zc.async.job.Job(first_job, job))
    >>> transaction.commit()

    >>> wait_repeatedly()
    ... # doctest: +ELLIPSIS
    TIME OUT...

    >>> job.result
    ['first', 'second', 'third']

    Be warned, these sort of constructs allow infinite loops!

.. [#extra_parallel_tricks] The ``parallel`` helper can accept a partial closure
    for a ``postprocess`` argument.

    >>> def postprocess(extra_info, *jobs):
    ...     return extra_info, sum(j.result for j in jobs)
    ...
    >>> job = queue.put(zc.async.job.parallel(
    ...     job_A, job_B, job_C,
    ...     postprocess=zc.async.job.Job(postprocess, 'foo')))

    >>> transaction.commit()

    >>> wait_repeatedly()
    ... # doctest: +ELLIPSIS
    TIME OUT...

    >>> job.result
    ('foo', 42)

    The list of jobs can be extended by adding them to the args of the job
    returned by ``parallel`` under these circumstances:

    - before the job has started,

    - by an inner job while it is running,

    - by any callback added to any inner job *before* that inner job has begun.

    Here's an example.

    >>> def postprocess(*jobs):
    ...     return [j.result for j in jobs]
    ...
    >>> job = queue.put(zc.async.job.parallel(postprocess=postprocess))
    >>> def second_job():
    ...     return 'second'
    ...
    >>> def third_job():
    ...     return 'third'
    ...
    >>> def schedule_third(main_job, ignored):
    ...     main_job.args.append(zc.async.job.Job(third_job))
    ...
    >>> def first_job(main_job):
    ...     j = zc.async.job.Job(second_job)
    ...     main_job.args.append(j)
    ...     j.addCallback(zc.async.job.Job(schedule_third, main_job))
    ...     return 'first'
    ...
    >>> job.args.append(zc.async.job.Job(first_job, job))
    >>> transaction.commit()

    >>> wait_repeatedly()
    ... # doctest: +ELLIPSIS
    TIME OUT...

    >>> job.result
    ['first', 'second', 'third']

    As with ``serial``, be warned, these sort of constructs allow infinite
    loops!

.. [#stop_usage_reactor]

    >>> threads = []
    >>> for queue_pools in dispatcher.queues.values():
    ...     for pool in queue_pools.values():
    ...         threads.extend(pool.threads)
    >>> reactor.stop()
    >>> zc.async.testing.wait_for_deactivation(dispatcher)
    >>> for thread in threads:
    ...     thread.join(3)
    ...
    >>> pprint.pprint(dispatcher.getStatistics()) # doctest: +ELLIPSIS
    {'failed': 2,
     'longest active': None,
     'longest failed': (..., 'unnamed'),
     'longest successful': (..., 'unnamed'),
     'shortest active': None,
     'shortest failed': (..., 'unnamed'),
     'shortest successful': (..., 'unnamed'),
     'started': 54,
     'statistics end': datetime.datetime(2006, 8, 10, 15, 44, 22, 211),
     'statistics start': datetime.datetime(2006, 8, 10, 16, ...),
     'successful': 52,
     'unknown': 0}
