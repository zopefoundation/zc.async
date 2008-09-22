.. _configuration-without-zope-3:

==============================
Configuration (without Zope 3)
==============================

This section discusses setting up zc.async without Zope 3. Since Zope 3 is
ill-defined, we will be more specific: this describes setting up zc.async
without ZCML, without any zope.app packages, and with as few dependencies as
possible. A casual way of describing the dependencies is "ZODB, Twisted, and
zope.component," though we directly depend on some smaller packages and
indirectly on others [#specific_dependencies]_.

You may have one or two kinds of configurations for your software using
zc.async. The simplest approach is to have all processes able both to put items
in queues, and to perform them with a dispatcher. You can then use on-the-fly
ZODB configuration to determine what jobs, if any, each process' dispatcher
performs. If a dispatcher has no agents in a given queue, as we'll discuss
below, the dispatcher will not perform any job for that queue.

However, if you want to create some processes that can only put items in a
queue, and do not have a dispatcher at all, that is easy to do. We'll call this
a "client" process, and the full configuration a "client/server process". As
you might expect, the configuration of a client process is a subset of the
configuration of the client/server process.

The ``zc.async.configure`` module helps with basic configuration.  The
:ref:`quickstart-with-virtualenv` shows an example of using this for a very
:quick start.  The current text uses some of those conveniences, but focuses
more on understanding the underlying patterns, rather than the conveniences.

We will first describe setting up a client, non-dispatcher process, in which
you only can put items in a zc.async queue; and then describe setting up a
dispatcher client/server process that can be used both to request and to
perform jobs.

Configuring a Client Process
============================

Generally, zc.async configuration has four basic parts: component
registrations, ZODB setup, ZODB configuration, and process configuration.  For
a client process, we'll discuss required component registrations; ZODB
setup;  minimal ZODB configuration; process configuration; and then circle
back around for some optional component registrations.

--------------------------------
Required Component Registrations
--------------------------------

The required registrations can be installed for you by the
``zc.async.configure.base`` function. Most other examples in this package,
such as those in the :ref:`usage` section, use this in their
test setup.

Again, for a quick start, you might just want to use the helper
``zc.async.configure.base`` function, and move on to the `Required ZODB Set
Up`_ section below.

Here, though, we will go over each required registration to briefly explain
what they are.

You must have three adapter registrations: IConnection to
ITransactionManager, IPersistent to IConnection, and IPersistent to
ITransactionManager.

The ``zc.twist`` package provides all of these adapters.  However,
zope.app.keyreference also provides a version of the ``connection`` adapter
that is identical or very similar, and that should work fine if you are
already using that package in your application.

    >>> import zc.twist
    >>> import zope.component
    >>> zope.component.provideAdapter(zc.twist.transactionManager)
    >>> zope.component.provideAdapter(zc.twist.connection)
    >>> import ZODB.interfaces
    >>> zope.component.provideAdapter(
    ...     zc.twist.transactionManager, adapts=(ZODB.interfaces.IConnection,))

We also need to be able to adapt functions and methods to jobs.  The
zc.async.job.Job class is the expected implementation.

    >>> import types
    >>> import zc.async.interfaces
    >>> import zc.async.job
    >>> zope.component.provideAdapter(
    ...     zc.async.job.Job,
    ...     adapts=(types.FunctionType,),
    ...     provides=zc.async.interfaces.IJob)
    >>> zope.component.provideAdapter(
    ...     zc.async.job.Job,
    ...     adapts=(types.MethodType,),
    ...     provides=zc.async.interfaces.IJob)
    >>> zope.component.provideAdapter( # optional, rarely used
    ...     zc.async.job.Job,
    ...     adapts=(zc.twist.METHOD_WRAPPER_TYPE,),
    ...     provides=zc.async.interfaces.IJob)

The queue looks for the UUID utility to set the ``assignerUUID`` job attribute,
and may want to use it to optionally filter jobs during ``claim`` in the
future. Also, the dispatcher will look for a UUID utility if a UUID is not
specifically provided to its constructor.

    >>> from zc.async.instanceuuid import UUID
    >>> zope.component.provideUtility(
    ...     UUID, zc.async.interfaces.IUUID, '')

The UUID we register here is a UUID of the instance, which is expected
to uniquely identify the process when in production. It is stored in
the file specified by the ``ZC_ASYNC_UUID`` environment variable (or in
``os.join(os.getcwd(), 'uuid.txt')`` if this is not specified, for easy
initial experimentation with the package).

    >>> import uuid
    >>> import os
    >>> f = open(os.environ["ZC_ASYNC_UUID"])
    >>> uuid_hex = f.readline().strip()
    >>> f.close()
    >>> uuid = uuid.UUID(uuid_hex)
    >>> UUID == uuid
    True

The uuid.txt file is intended to stay in the instance home as a persistent
identifier.

Again, all of the required registrations above can be accomplished quickly with
``zc.async.configure.base``.

--------------------
Required ZODB Set Up
--------------------

On a basic level, zc.async needs a setup that supports good conflict
resolution.  Most or all production ZODB storages now have the necessary
APIs to support MVCC.

Of course, if you want to run multiple processes, you need ZEO. You should also
then make sure that your ZEO server installation has all the code that includes
conflict resolution, such as zc.queue, because, as of this writing, conflict
resolution happens in the ZEO server, not in clients.

A more subtle decision is whether to use multiple databases.  The zc.async
dispatcher can generate a lot of database churn.  It may be wise to put the
queue in a separate database from your content database(s).

The downsides to this option include the fact that you must be careful to
specify to which database objects belong; and that broken cross-database
references are not handled gracefully in the ZODB as of this writing.

We will use multiple databases for our example here, because we are trying to
demonstrate production-quality examples. We will show this with a pure-Python
approach, rather than the ZConfig approach usually used by Zope. If you know
ZConfig, that will be a reasonable approach as well; see zope.app.appsetup
for how Zope uses ZConfig to set up multidatabases.

In our example, we create two file storages. In production, you might likely
use ZEO; hooking ClientStorage up instead of FileStorage should be straight
forward.

    >>> databases = {}
    >>> import ZODB.FileStorage
    >>> storage = ZODB.FileStorage.FileStorage(
    ...     'main.fs', create=True)

    >>> async_storage = ZODB.FileStorage.FileStorage(
    ...     'async.fs', create=True)

    >>> from ZODB.DB import DB
    >>> databases[''] = db = DB(storage)
    >>> databases['async'] = async_db = DB(async_storage)
    >>> async_db.databases = db.databases = databases
    >>> db.database_name = ''
    >>> async_db.database_name = 'async'
    >>> conn = db.open()
    >>> root = conn.root()

------------------
ZODB Configuration
------------------

A Queue
-------

All we must have for a client to be able to put jobs in a queue is ... a queue.

For a quick start, the ``zc.async.subscribers`` module provides a subscriber to
a DatabaseOpened event that does the right dance. See
``multidb_queue_installer`` and ``queue_installer`` in that module, and you can
see that in use in :ref:`configuration-with-zope-3`. For now, though, we're taking
things step by step and explaining what's going on.

Dispatchers look for queues in a mapping off the root of the database in
a key defined as a constant: zc.async.interfaces.KEY.  This mapping should
generally be a zc.async.queue.Queues object.

If we were not using a multi-database for our example, we could simply install
the queues mapping with this line:
``root[zc.async.interfaces.KEY] = zc.async.queue.Queues()``.  We will need
something a bit more baroque.  We will add the queues mapping to the 'async'
database, and then make it available in the main database ('') with the proper
key.

    >>> conn2 = conn.get_connection('async')
    >>> import zc.async.queue
    >>> queues = conn2.root()['mounted_queues'] = zc.async.queue.Queues()

Note that the 'mounted_queues' key in the async database is arbitrary:
what we care about is the key in the database that the dispatcher will
see.

Now we add the object explicitly to conn2, so that the ZODB will know the
"real" database in which the object lives, even though it will be also
accessible from the main database.

    >>> conn2.add(queues)
    >>> root[zc.async.interfaces.KEY] = queues
    >>> import transaction
    >>> transaction.commit()

Now we need to put a queue in the queues collection.  We can have more than
one, as discussed below, but we suggest a convention of the primary queue
being available in a key of '' (empty string).

    >>> queue = queues[''] = zc.async.queue.Queue()
    >>> transaction.commit()

Quotas
------

We touched on quotas in the usage section.  Some jobs will need to
access resources that are shared across processes.  A central data
structure such as an index in the ZODB is a prime example, but other
examples might include a network service that only allows a certain
number of concurrent connections.  These scenarios can be helped by
quotas.

Quotas are demonstrated in the usage section.  For configuration, you
should know these characteristics:

- you cannot add a job with a quota name that is not defined in the
  queue [#undefined_quota_name]_;

- you cannot add a quota name to a job in a queue if the quota name is not
  defined in the queue [#no_mutation_to_undefined]_;

- you can create and remove quotas on the queue [#create_remove_quotas]_;

- you can remove quotas if pending jobs have their quota names--the quota name
  is then ignored [#remove_quotas]_;

- quotas default to a size of 1 [#default_size]_;

- this can be changed at creation or later [#change_size]_; and

- decreasing the size of a quota while the old quota size is filled will
  not affect the currently running jobs [#decreasing_affects_future]_.

Multiple Queues
---------------

Since we put our queues in a mapping of them, we can also create multiple
queues.  This can make some scenarios more convenient and simpler to reason
about.  For instance, while you might have agents filtering jobs as we
describe above, it might be simpler to say that you have a queue for one kind
of job--say, processing a video file or an audio file--and a queue for other
kinds of jobs.  Then it is easy and obvious to set up simple FIFO agents
as desired for different dispatchers.  The same kind of logic could be
accomplished with agents, but it is easier to picture the multiple queues.

Another use case for multiple queues might be for specialized queues, like ones
that broadcast jobs. You could write a queue subclass that broadcasts copies of
jobs they get to all dispatchers, aggregating results.  This could be used to
send "events" to all processes, or to gather statistics on certain processes,
and so on.

Generally, any time the application wants to be able to assert a kind of job
rather than letting the agents decide what to do, having separate queues is
a reasonable tool.

---------------------
Process Configuration
---------------------

Daemonization
-------------

You often want to daemonize your software, so that you can restart it if
there's a problem, keep track of it and monitor it, and so on.  ZDaemon
(http://pypi.python.org/pypi/zdaemon) and Supervisor (http://supervisord.org/)
are two fairly simple-to-use ways of doing this for both client and
client/server processes. If your main application can be packaged as a
setuptools distribution (egg or source release or even development egg) then
you can have your main application as a zc.async client and your dispatchers
running a separate zc.async-only main loop that simply includes your main
application as a dependency, so the necessary software is around. You may have
to do a bit more configuration on the client/server side to mimic global
registries such as zope.component registrations and so on between the client
and the client/servers, but this shouldn't be too bad.

UUID File Location
------------------

As discussed above, the instanceuuid module will look for an environmental
variable ``ZC_ASYNC_UUID`` to find the file name to use, and failing that will
use ``os.join(os.getcwd(), 'uuid.txt')``.  It's worth noting that daemonization
tools such as ZDaemon and Supervisor (3 or greater) make setting environment
values for child processes an easy (and repeatable) configuration file setting.

-----------------------------------------------------
Optional Component Registrations for a Client Process
-----------------------------------------------------

The only optional component registration potentially valuable for client
instances that only put jobs in the queue is registering an adapter from
persistent objects to a queue.  The ``zc.async.queue.getDefaultQueue`` adapter
does this for an adapter to the queue named '' (empty string).  Since that's
what we have from the `ZODB Configuration`_ above section, we'll register it.
Writing your own adapter is trivial, as you can see if you look at the
implementation of this function.

    >>> zope.component.provideAdapter(zc.async.queue.getDefaultQueue)
    >>> zc.async.interfaces.IQueue(root) is queue
    True

Configuring a Client/Server Process
===================================

Configuring a client/server process--something that includes a running
dispatcher--means doing everything described above, plus a bit more.  You
need to set up and start a reactor and dispatcher; configure agents as desired
to get the dispatcher to do some work; and optionally configure logging.

For a quick start, the ``zc.async.subscribers`` module has some conveniences
to start a threaded reactor and dispatcher, and to install agents.  You might
want to look at those to get started.  They are also used in the Zope 3
configuration (README_3).  Meanwhile, this document continues to go
step-by-step instead, to try and explain the components and configuration.

Even though it seems reasonable to first start a dispatcher and then set up its
agents, we'll first define a subscriber to create an agent. As we'll see below,
the dispatcher fires an event when it registers with a queue, and another when
it activates the queue. These events give you the opportunity to register
subscribers to add one or more agents to a queue, to tell the dispatcher what
jobs to perform. zc.async.agent.addMainAgentActivationHandler is a reasonable
starter: it adds a single agent named 'main' if one does not exist. The agent
has a simple indiscriminate FIFO policy for the queue. If you want to write
your own subscriber, look at this, or at the more generic subscriber in the
``zc.async.subscribers`` module.

Agents are an important part of the ZODB configuration, and so are described
more in depth below.

    >>> import zc.async.agent
    >>> zope.component.provideHandler(
    ...     zc.async.agent.addMainAgentActivationHandler)

This subscriber is registered for the IDispatcherActivated event; another
approach might use the IDispatcherRegistered event.

-----------------------
Starting the Dispatcher
-----------------------

Now we can start the reactor, and start the dispatcher.
In some applications this may be done with an event subscriber to
DatabaseOpened, as is done in ``zc.async.subscribers``. Here, we will do it
inline.

Any object that conforms to the specification of zc.async.interfaces.IReactor
will be usable by the dispatcher.  For our example, we will use our own instance
of the Twisted select-based reactor running in a separate thread.  This is
separate from the Twisted reactor installed in twisted.internet.reactor, and
so this approach can be used with an application that does not otherwise use
Twisted (for instance, a Zope application using the "classic" zope publisher).

The testing module also has a reactor on which the `Usage` section relies, if
you would like to see a minimal contract.

Configuring the basics is fairly simple, as we'll see in a moment.  The
trickiest part is to handle signals cleanly. It is also optional! The
dispatcher will eventually figure out that there was not a clean shut down
before and take care of it. Here, though, essentially as an optimization, we
install signal handlers in the main thread using ``reactor._handleSignals``.
``reactor._handleSignals`` may work in some real-world applications, but if
your application already needs to handle signals you may need a more careful
approach. Again, see ``zc.async.subscribers`` for some options you can explore.

    >>> import twisted.internet.selectreactor
    >>> reactor = twisted.internet.selectreactor.SelectReactor()
    >>> reactor._handleSignals()

Now we are ready to instantiate our dispatcher.

    >>> import zc.async.dispatcher
    >>> dispatcher = zc.async.dispatcher.Dispatcher(db, reactor)

Notice it has the uuid defined in instanceuuid.

    >>> dispatcher.UUID == UUID
    True

Now we can start the reactor and the dispatcher in a thread.

    >>> import threading
    >>> def start():
    ...     dispatcher.activate()
    ...     reactor.run(installSignalHandlers=0)
    ...
    >>> thread = threading.Thread(target=start)
    >>> thread.setDaemon(True)

    >>> thread.start()

The dispatcher should be starting up now.  Let's wait for it to activate.
We're using a test convenience, get_poll, defined in the testing module.

    >>> from zc.async.testing import get_poll
    >>> poll = get_poll(dispatcher, 0)

We're off!  The events have been fired for registering and activating the
dispatcher.  Therefore, our subscriber to add our agent has fired.

We need to begin our transaction to synchronize our view of the database.

    >>> t = transaction.begin()

We get the collection of dispatcher agents from the queue, using the UUID.

    >>> dispatcher_agents = queue.dispatchers[UUID]

It has one agent--the one placed by our subscriber.

    >>> dispatcher_agents.keys()
    ['main']
    >>> agent = dispatcher_agents['main']

Now we have our agent!  But...what is it [#stop_config_reactor]_?

------
Agents
------

Agents are the way you control what a dispatcher's worker threads do.  They
pick the jobs and assign them to their dispatcher when the dispatcher asks.

*If a dispatcher does not have any agents in a given queue, it will not perform
any tasks for that queue.*

We currently have an agent that simply asks for the next available FIFO job.
We are using an agent implementation that allows you to specify a callable to
filter the job.  That callable is now None.

    >>> agent.filter is None
    True

What does a filter do?  A filter takes a job and returns a value evaluated as a
boolean.  For instance, let's say we always wanted a certain number of threads
available for working on a particular call; for the purpose of example, we'll
use ``operator.mul``, though a more real-world example might be a network call
or a particular call in your application.

    >>> import operator
    >>> def chooseMul(job):
    ...     return job.callable == operator.mul
    ...

You might want something more sophisticated, such as preferring operator.mul,
but if one is not in the queue, it will take any; or doing any other priority
variations.  To do this, you'll want to write your own agent--possibly
inheriting from the provided one and overriding ``_choose``.

Let's set up another agent, in addition to the default one, that has
the ``chooseMul`` policy.

    >>> agent2 = dispatcher_agents['mul'] = zc.async.agent.Agent(chooseMul)

Another characteristic of agents is that they specify how many jobs they
should pick at a time.  The dispatcher actually adjusts the size of the
ZODB connection pool to accommodate its agents' size.  The default is 3.

    >>> agent.size
    3
    >>> agent2.size
    3

We can change that at creation or later.

Finally, it's worth noting that agents contain the jobs that are currently
worked on by the dispatcher, on their behalf; and have a ``completed``
collection of the more recent completed jobs, beginning with the most recently
completed job.

----------------------
Logging and Monitoring
----------------------

Logs are sent to the ``zc.async.events`` log for big events, like startup and
shutdown, and errors.  Poll and job logs are sent to ``zc.async.trace``.
Configure the standard Python logging module as usual to send these logs where
you need.  Be sure to auto-rotate the trace logs.

The package supports monitoring using zc.monitor.  Using this package includes
only a very few additional dependencies: zc.monitor, simplejson, and zc.ngi. An
example of setting it up without Zope 3 is in the end of
:ref:`quickstart-with-virtualenv`.  If you would like to use it, see that
document, monitor.txt in the package, and our next section:
:ref:`configuration-with-zope-3`. 

Otherwise, if you want to roll your own monitoring, glance at monitor.py and
monitordb.py--you'll see that you should be able to reuse most of the heavy
lifting, so it should be pretty easy to hook up the basic data another way.

    >>> reactor.stop()

.. rubric:: Footnotes

.. [#specific_dependencies]  More specifically, as of this writing,
    these are the minimal egg dependencies (including indirect
    dependencies):

    - pytz
        A Python time zone library

    - rwproperty
        A small package of descriptor conveniences

    - uuid
        The uuid module included in Python 2.5

    - zc.dict
        A ZODB-aware dict implementation based on BTrees.

    - zc.queue
        A ZODB-aware queue

    - zc.twist
        Conveniences for working with Twisted and the ZODB

    - twisted
        The Twisted internet library.

    - ZConfig
        A general configuration package coming from the Zope project with which
        the ZODB tests.

    - zdaemon
        A general daemon tool coming from the Zope project.

    - ZODB3
        The Zope Object Database.

    - zope.bforest
        Aggregations of multiple BTrees into a single dict-like structure,
        reasonable for rotating data structures, among other purposes.

    - zope.component
        A way to hook together code by contract.

    - zope.deferredimport
        A way to defer imports in Python packages, often to prevent circular
        import problems.

    - zope.deprecation
        A small framework for deprecating features.

    - zope.event
        An exceedingly small event framework that derives its power from
        zope.component.

    - zope.i18nmessageid
        A way to specify strings to be translated.

    - zope.interface
        A way to specify code contracts and other data structures.

    - zope.proxy
        A way to proxy other Python objects.

    - zope.testing
        Testing extensions and helpers.

    The next section, :ref:`configuration-with-zope-3`, still tries to limit
    dependencies--we only rely on additional packages zc.z3monitor, simplejson,
    and zope.app.appsetup ourselves--but as of this writing zope.app.appsetup
    ends up dragging in a large chunk of zope.app.* packages. Hopefully that
    will be refactored in Zope itself, and our full Zope 3 configuration can
    benefit from the reduced indirect dependencies.

.. [#undefined_quota_name]

    >>> import operator
    >>> import zc.async.job
    >>> job = zc.async.job.Job(operator.mul, 5, 2)
    >>> job.quota_names = ['content catalog']
    >>> job.quota_names
    ('content catalog',)
    >>> queue.put(job)
    Traceback (most recent call last):
    ...
    ValueError: ('unknown quota name', 'content catalog')
    >>> len(queue)
    0

.. [#no_mutation_to_undefined]

    >>> job.quota_names = ()
    >>> job is queue.put(job)
    True
    >>> job.quota_names = ('content catalog',)
    Traceback (most recent call last):
    ...
    ValueError: ('unknown quota name', 'content catalog')
    >>> job.quota_names
    ()

.. [#create_remove_quotas]

    >>> list(queue.quotas)
    []
    >>> queue.quotas.create('testing')
    >>> list(queue.quotas)
    ['testing']
    >>> queue.quotas.remove('testing')
    >>> list(queue.quotas)
    []

.. [#remove_quotas]

    >>> queue.quotas.create('content catalog')
    >>> job.quota_names = ('content catalog',)
    >>> queue.quotas.remove('content catalog')
    >>> job.quota_names
    ('content catalog',)
    >>> job is queue.claim()
    True
    >>> len(queue)
    0

.. [#default_size]

    >>> queue.quotas.create('content catalog')
    >>> queue.quotas['content catalog'].size
    1

.. [#change_size]

    >>> queue.quotas['content catalog'].size = 2
    >>> queue.quotas['content catalog'].size
    2
    >>> queue.quotas.create('frobnitz account', size=3)
    >>> queue.quotas['frobnitz account'].size
    3

.. [#decreasing_affects_future]

    >>> job1 = zc.async.job.Job(operator.mul, 5, 2)
    >>> job2 = zc.async.job.Job(operator.mul, 5, 2)
    >>> job3 = zc.async.job.Job(operator.mul, 5, 2)
    >>> job1.quota_names = job2.quota_names = job3.quota_names = (
    ...     'content catalog',)
    >>> job1 is queue.put(job1)
    True
    >>> job2 is queue.put(job2)
    True
    >>> job3 is queue.put(job3)
    True
    >>> job1 is queue.claim()
    True
    >>> job2 is queue.claim()
    True
    >>> print queue.claim()
    None
    >>> quota = queue.quotas['content catalog']
    >>> len(quota)
    2
    >>> list(quota) == [job1, job2]
    True
    >>> quota.filled
    True
    >>> quota.size = 1
    >>> quota.filled
    True
    >>> print queue.claim()
    None
    >>> job1()
    10
    >>> print queue.claim()
    None
    >>> len(quota)
    1
    >>> list(quota) == [job2]
    True
    >>> job2()
    10
    >>> job3 is queue.claim()
    True
    >>> list(quota) == [job3]
    True
    >>> len(quota)
    1
    >>> job3()
    10
    >>> print queue.claim()
    None
    >>> len(queue)
    0
    >>> quota.clean()
    >>> len(quota)
    0
    >>> quota.filled
    False

.. [#stop_config_reactor] We don't want the live dispatcher for our demos,
    actually.  See dispatcher.txt to see the live dispatcher actually in use.
    So, here we'll stop the "real" reactor and switch to a testing one.

    >>> reactor.callFromThread(reactor.stop)
    >>> thread.join(3)
    >>> assert not dispatcher.activated, 'dispatcher did not deactivate'

    >>> import zc.async.testing
    >>> reactor = zc.async.testing.Reactor()
    >>> dispatcher._reactor = reactor
    >>> dispatcher.activate()
    >>> reactor.start()
