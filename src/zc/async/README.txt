~~~~~~~~
zc.async
~~~~~~~~

.. contents::

============
Introduction
============

Goals
=====

The zc.async package provides a way to schedule jobs to be performed
out-of-band from your current thread.  The job might be done in another thread
or another process, possibly on another machine.  Here are some example core
use cases.

- You want to let users do something that requires a lot of system
  resources from your application, such as creating a large PDF.  Naively
  done, six or seven simultaneous PDF requests will consume your
  application thread pool and could make your application unresponsive to
  any other users.

- You want to let users spider a web site; communicate with a credit card
  company; query a large, slow LDAP database on another machine; or do
  some other action that generates network requests from the server.
  System resources might not be a problem, but, again, if something goes
  wrong, several requests could make your application unresponsive.

- Perhaps because of resource contention, you want to serialize work
  that can be done asynchronously, such as updating a single data structure
  like a catalog index.

- You want to decompose and parallelize a single job across many machines so
  it can be finished faster.

- You have an application job that you discover is taking longer than users can
  handle, even after you optimize it.  You want a quick fix to move the work
  out-of-band.

Many of these core use cases involve end-users being able to start potentially
expensive processes, on demand.  Basic scheduled tasks are also provided by this
package, though recurrence must be something you arrange.

History
=======

This is a second-generation design.  The first generation was `zasync`,
a mission-critical and successful Zope 2 product in use for a number of
high-volume Zope 2 installations.  [#history]_ It's worthwhile noting
that zc.async has absolutely no backwards compatibility with zasync and
zc.async does not require Zope (although it can be used in conjuction with it,
details below).

Design Overview
===============

---------------
Overview: Usage
---------------

Looking at the design from the perspective of regular usage, your code obtains
a ``queue``, which is a place to register jobs to be performed asynchronously.

Your application calls ``put`` on the queue to register a job.  The job must be
a pickleable, callable object; a global function, a callable persistent object,
a method of a persistent object, or a special zc.async.job.Job object
(discussed later) are all examples of suitable objects.  The job by default is
registered to be performed as soon as possible, but can be registered to be
called at a certain time.

The ``put`` call will return a zc.async.job.Job object.  This object represents
both the callable and its deferred result.  It has information about the job
requested, the current state of the job, and the result of performing the job.

An example spelling for registering a job might be ``self.pending_result =
queue.put(self.performSpider)``.  The returned object can be stored and polled
to see when the job is complete; or the job can be configured to do additional
work when it completes (such as storing the result in a data structure).

-------------------
Overview: Mechanism
-------------------

Multiple processes, typically spread across multiple machines, can
connect to the queue and claim and perform work.  As with other
collections of processes that share pickled objects, these processes
generally should share the same software (though some variations on this
constraint should be possible).

A process that should claim and perform work, in addition to a database
connection and the necessary software, needs a ``dispatcher`` with a
``reactor`` to provide a heartbeat.  The dispatcher will rely on one or more
persistent ``agents`` in the queue (in the database) to determine which jobs
it should perform.

A ``dispatcher`` is in charge of dispatching queued work for a given
process to worker threads.  It works with one or more queues and a
single reactor.  It has a universally unique identifier (UUID), which is
usually an identifier of the application instance in which it is
running.  The dispatcher starts jobs in dedicated threads.

A ``reactor`` is something that can provide an eternal loop, or heartbeat,
to power the dispatcher.  It can be the main twisted reactor (in the
main thread); another instance of a twisted reactor (in a child thread);
or any object that implements a small subset of the twisted reactor
interface (see discussion in dispatcher.txt, and example testing reactor in
testing.py, used below).

An ``agent`` is a persistent object in a queue that is associated with a
dispatcher and is responsible for picking jobs and keeping track of
them. Zero or more agents within a queue can be associated with a
dispatcher.  Each agent for a given dispatcher in a given queue is
identified uniquely with a name [#identifying_agent]_.

Generally, these work together as follows.  The reactor calls the
dispatcher. The dispatcher tries to find the mapping of queues in the
database root under a key of ``zc.async`` (see constant
zc.async.interfaces.KEY).  If it finds the mapping, it iterates
over the queues (the mapping's values) and asks each queue for the
agents associated with the dispatcher's UUID.  The dispatcher then is
responsible for seeing what jobs its agents want to do from the queue,
and providing threads and connections for the work to be done.  The
dispatcher then asks the reactor to call itself again in a few seconds.

Reading More
============

This document continues on with three other main sections: `Usage`_,
`Configuration without Zope 3`_, and `Configuration with Zope 3`_.

Other documents in the package are primarily geared as maintainer
documentation, though the author has tried to make them readable and
understandable.

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
examples, we will use a helper function called ``wait_for`` to wait for
the job to be completed [#wait_for]_.

    >>> wait_for(job)
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

    >>> wait_for(job)
    >>> root['demo'].counter
    1

The method was called, and the persistent object modified!

To reiterate, only pickleable callables such as global functions and the
methods of persistent objects can be used. This rules out, for instance,
lambdas and other functions created dynamically. As we'll see below, the job
instance can help us out there somewhat by offering closure-like features.

--------------
``queue.pull``
--------------

If you put a job into a queue and it hasn't been claimed yet and you want to
cancel the job, ``pull`` it from the queue.

    >>> len(queue)
    0
    >>> job = queue.put(send_message)
    >>> len(queue)
    1
    >>> job is queue.pull()
    True
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
    >>> wait_for(job, attempts=2) # +5 virtual seconds
    TIME OUT
    >>> wait_for(job, attempts=2) # +5 virtual seconds
    TIME OUT
    >>> datetime.datetime.now(pytz.UTC)
    datetime.datetime(2006, 8, 10, 15, 44, 43, 211, tzinfo=<UTC>)

    >>> zc.async.testing.set_now(datetime.datetime(
    ...     2006, 8, 10, 15, 56, tzinfo=pytz.UTC))
    >>> wait_for(job)
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

The result of a call to `put` returns an IJob.  The
job represents the pending result.  This object has a lot of
functionality that's explored in other documents in this package, and
demonstrated a bit below, but here's a summary.

- You can introspect, and even modify, the call and its
  arguments.

- You can specify that the job should be run serially with others
  of a given identifier.

- You can specify other calls that should be made on the basis of the
  result of this call.

- You can persist a reference to it, and periodically (after syncing
  your connection with the database, which happens whenever you begin or
  commit a transaction) check its `state` to see if it is equal to
  zc.async.interfaces.COMPLETED.  When it is, the call has run to
  completion, either to success or an exception.

- You can look at the result of the call (once COMPLETED).  It might be
  the result you expect, or a zc.twist.Failure, which is a
  subclass of twisted.python.failure.Failure, way to safely communicate
  exceptions across connections and machines and processes.

-------
Results
-------

So here's a simple story.  What if you want to get a result back from a
call?  Look at the job.result after the call is COMPLETED.

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
    >>> wait_for(job)
    >>> t = transaction.begin()
    >>> job.result
    '200 OK'
    >>> job.status == zc.async.interfaces.COMPLETED
    True

--------
Closures
--------

What's more, you can pass a Job to the `put` call.  This means that you
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
    >>> wait_for(job)
    >>> t = transaction.begin()
    >>> root['demo'].counter
    6

With keyword arguments (``value``):

    >>> job = queue.put(
    ...     zc.async.job.Job(root['demo'].increase, value=10))
    >>> transaction.commit()
    >>> wait_for(job)
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
    >>> wait_for(job)
    >>> t = transaction.begin()
    >>> job.result
    <zc.twist.Failure exceptions.NameError>

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
    >>> wait_for(job)
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
    >>> wait_for(job)
    >>> job.result
    <zc.twist.Failure exceptions.NameError>
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
    will wait that at least that number of seconds until an annotation of the
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

Let's give the first three a whirl.  We will write a function that
examines the job's state while it is being called, and sets the state in
an annotation, then waits for our flag to finish.

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
    >>> wait_for(job)
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
    >>> wait_for(job1, job2)
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
    >>> wait_for(job1)
    >>> wait_for(job2)
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
    >>> wait_for(job, attempts=3)
    TIME OUT
    >>> wait_for(job, attempts=3)
    >>> job.result
    42

The second_job could also have returned a job, allowing for additional
legs.  Once the last job returns a real result, it will cascade through the
past jobs back up to the original one.

A different approach could have used callbacks.  Using callbacks can be
somewhat more complicated to follow, but can allow for a cleaner
separation of code: dividing code that does work from code that
orchestrates the jobs.  We'll see an example of the idea below.

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
``post_process`` will be a function that assembles the job results for a
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
    >>> def post_process(*args):
    ...     # this callable represents one that needs to wait for the
    ...     # parallel jobs to be done before it can process them and return
    ...     # the final result
    ...     return sum(args)
    ...

Now this code works with jobs to get everything done.  Note, in the
callback function, that mutating the same object we are checking
(job.args) is the way we are enforcing necessary serializability
with MVCC turned on.

    >>> def callback(job, result):
    ...     job.args.append(result)
    ...     if len(job.args) == 3: # all results are in
    ...         zc.async.local.getJob().queue.put(job)
    ...
    >>> def main_job():
    ...     job = zc.async.job.Job(post_process)
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
    >>> wait_for(job, attempts=3)
    TIME OUT
    >>> wait_for(job, attempts=3)
    TIME OUT
    >>> wait_for(job, attempts=3)
    TIME OUT
    >>> wait_for(job, attempts=3)
    >>> job.result
    42

Ta-da!

For real-world usage, you'd also probably want to deal with the possibility of
one or more of the jobs generating a Failure, among other edge cases.

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
    >>> wait_for(job)
    >>> job.result
    '200 OK'

Conclusion
==========

This concludes our discussion of zc.async usage. The `next section`_ shows how
to configure zc.async without Zope 3 [#stop_usage_reactor]_.

.. _next section: `Configuration without Zope 3`_

.. ......... ..
.. Footnotes ..
.. ......... ..

.. [#history] The first generation, zasync, had the following goals:

    - be scalable, so that another process or machine could do the
      asynchronous work;

    - support lengthy jobs outside of the ZODB;

    - support lengthy jobs inside the ZODB;

    - be recoverable, so that crashes would not lose work;

    - be discoverable, so that logs and web interfaces give a view into
      the work being done asynchronously;

    - be easily extendible, to do new jobs; and

    - support graceful job expiration and cancellation.

    It met its goals well in some areas and adequately in others.

    Based on experience with the first generation, this second
    generation identifies several areas of improvement from the first
    design, and adds several goals.

    - Improvements

      * More carefully delineate the roles of the comprising components.

        The zasync design has three main components, as divided by their
        roles: persistent deferreds, now called jobs; job queues (the
        original zasync's "asynchronous call manager"); and dispatchers
        (the original zasync ZEO client).  The zasync 1.x design
        blurred the lines between the three components such that the
        component parts could only be replaced with difficulty, if at
        all. A goal for the 2.x design is to clearly define the role for
        each of three components such that, for instance, a user of a
        queue does not need to know about the dispatcher ot the agents.

      * Improve scalability of asynchronous workers.

        The 1.x line was initially designed for a single asynchronous
        worker, which could be put on another machine thanks to ZEO.
        Tarek Ziad of Nuxeo wrote zasyncdispatcher, which allowed
        multiple asynchronous workers to accept work, allowing multiple
        processes and multiple machines to divide and conquer. It worked
        around the limitations of the original zasync design to provide
        even more scalability. However, it was forced to divide up work
        well before a given worker looks at the queue.

        While dividing work earlier allows guesses and heuristics a
        chance to predict what worker might be more free in the future,
        a more reliable approach is to let the worker gauge whether it
        should take a job at the time the job is taken. Perhaps the
        worker will choose based on the worker's load, or other
        concurrent jobs in the process, or other details. A goal for the
        2.x line is to more directly support this type of scalability.

      * Improve scalability of registering jobs.

        The 1.x line initially wasn't concerned about very many
        concurrent asynchronous requests.  When this situation was
        encountered, it caused ConflictErrors between the worker process
        reading the deferred queue and the code that was adding the
        deferreds.  Thanks to Nuxeo, this problem was addressed in the
        1.x line.  A goal for the new version is to include and improve
        upon the 1.x solution.

      * Make it even simpler to provide new jobs.

        In the first version, `plugins` performed jobs.  They had a
        specific API and they had to be configured.  A goal for the new
        version is to require no specific API for jobs, and to not
        require any configuration.

      * Improve report information, especially through the web.

        The component that the first version of zasync provided to do
        the asynchronous work, the zasync client, provided very verbose
        logs of the jobs done, but they were hard to read and also did
        not have a through- the-web parallel.  Two goals for the new
        version are to improve the usefulness of the filesystem logs and
        to include more complete through-the-web visibility of the
        status of the provided asynchronous clients.

      * Make it easier to configure and start, especially for small
        deployments.

        A significant barrier to experimentation and deployment of the
        1.x line was the difficulty in configuration.  The 1.x line
        relied on ZConfig for zasync client configuration, demanding
        non-extensible similar-yet-subtly-different .conf files like the
        Zope conf files. The 2.x line plans to provide code that Zope 3
        can configure to run in the same process as a standard Zope 3
        application.  This means that development instances can start a
        zasync quickly and easily.  It also means that processes can be
        reallocated on the fly during production use, so that a machine
        being used as a zasync process can quickly be converted to a web
        server, if needed, and vice versa.  It further means that the
        Zope web server can be used for through-the-web reports of the
        current zasync process state.

    - New goals

      * Support intermediate return calls so that jobs can report back
        how they are doing.

        A frequent request from users of zasync 1.x was the ability for
        a long- running asynchronous process to report back progress to
        the original requester.  The 2.x line addresses this with three
        changes:

        + jobs are annotatable;

        + jobs should not be modified in an asynchronous
          worker that does work (though they may be read);

        + jobs can request another job in a synchronous process
          that annotates the job with progress status or other
          information.

        Because of relatively recent changes in ZODB--multi version
        concurrency control--this simple pattern should not generate
        conflict errors.

      * Support time-delayed calls.

        Retries and other use cases make time-delayed deferred calls
        desirable. The new design supports these sort of calls.

.. [#identifying_agent] The combination of a queue name plus a
    dispatcher UUID plus an agent name uniquely identifies an agent.

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
    available for you to set this stuff up if you'd like, though it's not too
    onerous to do it by hand.

    We'll use a test reactor that we can control.

    >>> import zc.async.testing
    >>> reactor = zc.async.testing.Reactor()
    >>> reactor.start() # this mokeypatches datetime.datetime.now

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
    >>> agent.chooser is zc.async.agent.chooseFirst
    True
    >>> agent.size
    3
    >>> transaction.commit()

.. [#wait_for] This is our helper function.  It relies on the test fixtures
    set up in the previous footnote.

    >>> import time
    >>> def wait_for(*jobs, **kwargs):
    ...     reactor.time_flies(dispatcher.poll_interval) # starts thread
    ...     # now we wait for the thread
    ...     for i in range(kwargs.get('attempts', 10)):
    ...         while reactor.time_passes():
    ...             pass
    ...         transaction.begin()
    ...         for j in jobs:
    ...             if j.status != zc.async.interfaces.COMPLETED:
    ...                 break
    ...         else:
    ...             break
    ...         time.sleep(0.1)
    ...     else:
    ...         print 'TIME OUT'
    ...

.. [#commit_for_multidatabase] We commit before we do the next step as a
    good practice, in case the queue is from a different database than
    the root.  See the configuration sections for a discussion about
    why putting the queue in another database might be a good idea.

    Rather than committing the transaction,
    ``root._p_jar.add(root['demo'])`` would also accomplish the same
    thing from a multi-database perspective, without a commit.  It was
    not used in the example because the ``transaction.commit()`` the author
    judged it to be less jarring to the reader.  If you are down here
    reading this footnote, maybe the author was wrong. :-)

.. [#already_passed]

    >>> t = transaction.begin()
    >>> job = queue.put(
    ...     send_message, datetime.datetime(2006, 8, 10, 15, tzinfo=pytz.UTC))
    >>> transaction.commit()
    >>> wait_for(job)
    imagine this sent a message to another machine

    It's worth noting that this situation consitutes a small exception
    in the handling of scheduled calls.  Scheduled calls usually get
    preference when jobs are handed out over normal non-scheduled "as soon as
    possible" jobs.  However, setting the begin_after date to an earlier
    time puts the job at the end of the (usually) FIFO queue of non-scheduled
    tasks: it is treated exactly as if the date had not been specified.

.. [#already_passed_timed_out]

    >>> t = transaction.begin()
    >>> job = queue.put(
    ...     send_message, datetime.datetime(2006, 7, 21, 12, tzinfo=pytz.UTC))
    >>> transaction.commit()
    >>> wait_for(job)
    >>> job.result
    <zc.twist.Failure zc.async.interfaces.AbortedError>
    >>> import sys
    >>> job.result.printTraceback(sys.stdout) # doctest: +NORMALIZE_WHITESPACE
    Traceback (most recent call last):
    Failure: zc.async.interfaces.AbortedError:

.. [#job] The Job class can take arguments and keyword arguments
    for the wrapped callable at call time as well, similar to Python
    2.5's `partial`.  This will be important when we use the Job as
    a callback.  For this use case, though, realize that the job
    will be called with no arguments, so you must supply all necessary
    arguments for the callable on creation time.

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
     'longest active': ('\x00...', 'unnamed'),
     'longest failed': ('\x00...', 'unnamed'),
     'longest successful': ('\x00...', 'unnamed'),
     'shortest active': ('\x00\...', 'unnamed'),
     'shortest failed': ('\x00\...', 'unnamed'),
     'shortest successful': ('\x00...', 'unnamed'),
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
    {'call': "<zc.async.job.Job (oid ..., db 'unnamed') ``zc.async.doctest_test.annotateStatus()``>",
     'completed': None,
     'failed': False,
     'poll id': ...,
     'quota names': (),
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
     'longest failed': ('\x00...', 'unnamed'),
     'longest successful': ('\x00...', 'unnamed'),
     'shortest active': None,
     'shortest failed': ('\x00\...', 'unnamed'),
     'shortest successful': ('\x00...', 'unnamed'),
     'started': 10,
     'statistics end': datetime.datetime(2006, 8, 10, 15, 46, 52, 211),
     'statistics start': datetime.datetime(2006, 8, 10, 15, 56, 52, 211),
     'successful': 8,
     'unknown': 0}

    Although, wait a second--the 'statistics end', the 'started', and the
    'successful' values have changed!  Why?

    To keep memory from rolling out of control, the dispatcher by default
    only keeps 10 to 12.5 minutes worth of poll information in memory.  For
    the rest, keep logs and look at them (...and rotate them!).

    The ``getActiveJobIds`` list shows the new task--which is completed, but
    not as of the last poll, so it's still in the list.

    >>> job_ids = dispatcher.getActiveJobIds()
    >>> len(job_ids)
    1
    >>> info = dispatcher.getJobInfo(*job_ids[0])
    >>> pprint.pprint(info) # doctest: +ELLIPSIS
    {'call': "<zc.async.job.Job (oid ..., db 'unnamed') ``zc.async.doctest_test.annotateStatus()``>",
     'completed': datetime.datetime(...),
     'failed': False,
     'poll id': ...,
     'quota names': (),
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

.. [#stop_usage_reactor]

    >>> pprint.pprint(dispatcher.getStatistics()) # doctest: +ELLIPSIS
    {'failed': 2,
     'longest active': None,
     'longest failed': ('\x00...', 'unnamed'),
     'longest successful': ('\x00...', 'unnamed'),
     'shortest active': None,
     'shortest failed': ('\x00\...', 'unnamed'),
     'shortest successful': ('\x00...', 'unnamed'),
     'started': 22,
     'statistics end': datetime.datetime(2006, 8, 10, 15, 46, 52, 211),
     'statistics start': datetime.datetime(2006, 8, 10, 15, 57, 47, 211),
     'successful': 20,
     'unknown': 0}
    >>> reactor.stop()
