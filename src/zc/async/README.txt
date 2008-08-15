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
high-volume Zope 2 installations.  [#async_history]_ It's worthwhile noting
that zc.async has absolutely no backwards compatibility with zasync and
zc.async does not require Zope (although it can be used in conjunction with
it).

Design Overview
===============

---------------
Overview: Usage
---------------

Looking at the design from the perspective of regular usage, your code obtains
a ``queue``, which is a place to register jobs to be performed asynchronously.

Your application calls ``put`` on the queue to register a job.  The job must be
a pickleable, callable object.  A global function, a callable persistent
object, a method of a persistent object, or a special zc.async.job.Job object
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

.. rubric:: Footnotes

.. [#async_history] The first generation, ``zasync``, had the following goals:

    - be scalable, so that another process or machine could do the asynchronous
      work;

    - support lengthy jobs outside of the ZODB;

    - support lengthy jobs inside the ZODB;

    - be recoverable, so that crashes would not lose work;

    - be discoverable, so that logs and web interfaces give a view into the
      work being done asynchronously;

    - be easily extendible, to do new jobs; and

    - support graceful job expiration and cancellation.

    It met its goals well in some areas and adequately in others.

    Based on experience with the first generation, this second generation
    identifies several areas of improvement from the first design, and adds
    several goals.

    - Improvements

      * More carefully delineate the roles of the comprising components.

        The zc.async design has three main components, as divided by their
        roles: persistent deferreds, now called jobs; job queues (the original
        zasync's "asynchronous call manager"); and dispatchers (the original
        zasync ZEO client). The zasync 1.x design blurred the lines between the
        three components such that the component parts could only be replaced
        with difficulty, if at all. A goal for the 2.x design is to clearly
        define the role for each of three components such that, for instance, a
        user of a queue does not need to know about the dispatcher or the
        agents.

      * Improve scalability of asynchronous workers.

        The 1.x line was initially designed for a single asynchronous worker,
        which could be put on another machine thanks to ZEO. Tarek Ziade of
        Nuxeo wrote zasyncdispatcher, which allowed multiple asynchronous
        workers to accept work, allowing multiple processes and multiple
        machines to divide and conquer. It worked around the limitations of the
        original zasync design to provide even more scalability. However, it
        was forced to divide up work well before a given worker looks at the
        queue.

        While dividing work earlier allows guesses and heuristics a chance to
        predict what worker might be more free in the future, a more reliable
        approach is to let the worker gauge whether it should take a job at the
        time the job is taken. Perhaps the worker will choose based on the
        worker's load, or other concurrent jobs in the process, or other
        details. A goal for the 2.x line is to more directly support this type
        of scalability.

      * Improve scalability of registering jobs.

        The 1.x line initially wasn't concerned about very many concurrent
        asynchronous requests. When this situation was encountered, it caused
        ConflictErrors between the worker process reading the deferred queue
        and the code that was adding the deferreds. Thanks to Nuxeo, this
        problem was addressed in the 1.x line. A goal for the new version is to
        include and improve upon the 1.x solution.

      * Make it even simpler to provide new jobs.

        In the first version, `plugins` performed jobs. They had a specific API
        and they had to be configured. A goal for the new version is to require
        no specific API for jobs, and to not require any configuration.

      * Improve report information, especially through the web.

        The component that the first version of zasync provided to do the
        asynchronous work, the zasync client, provided very verbose logs of the
        jobs done, but they were hard to read and also did not have a through-
        the-web parallel. Two goals for the new version are to improve the
        usefulness of the filesystem logs and to include more complete
        visibility of the status of the provided asynchronous clients.

      * Make it easier to configure and start, especially for small
        deployments.

        A significant barrier to experimentation and deployment of the 1.x line
        was the difficulty in configuration. The 1.x line relied on ZConfig for
        zasync client configuration, demanding non-extensible
        similar-yet-subtly-different .conf files like the Zope conf files. The
        2.x line provides code that Zope 3 can configure to run in the same
        process as a standard Zope 3 application. This means that development
        instances can start a zasync quickly and easily. It also means that
        processes can be reallocated on the fly during production use, so that
        a machine being used as a zasync process can quickly be converted to a
        web server, if needed, and vice versa.

    - New goals

      * Support intermediate return calls so that jobs can report back how they
        are doing.

        A frequent request from users of zasync 1.x was the ability for a long-
        running asynchronous process to report back progress to the original
        requester. The 2.x line addresses this with three changes:

        + jobs are annotatable;

        + jobs should not be modified in an asynchronous worker that does work
          (though they may be read);

        + jobs can request another job in a synchronous process that annotates
          the job with progress status or other information.

        Because of relatively recent changes in ZODB--multi version concurrency
        control--this simple pattern should not generate conflict errors.

      * Support time-delayed calls.

        Retries and other use cases make time-delayed deferred calls desirable.
        The new design supports these sort of calls.

.. [#identifying_agent] The combination of a queue name plus a
    dispatcher UUID plus an agent name uniquely identifies an agent.
