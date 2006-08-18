========
zc.async
========

The zc.async package provides a way to make asynchronous application
calls.

Calls are handled by worker processes, each of which is typically a
standard Zope process, identified by a UUID [#uuid]_, that
may simultaneously perform other tasks (such as handle standard web
requests).  Each worker is responsible for claiming and performing calls
in its main thread or additional threads.  To have multiple workers on
the same queue of tasks, share the database with ZEO.

Pending calls and worker data objects are stored in a data manager
object in the ZODB.  This is typically stored in the root of the ZODB,
alongside the application object, with a key of 'zc.async.datamanager',
but the adapter that obtains the data manager can be replaced to point
to a different location.

Worker data objects have queues representing potential or current tasks
for the worker, in the main thread or a secondary thread.  Each worker
has a virtual loop, part of the Twisted main loop, for every worker
process, which is responsible for responding to system calls (like
pings) and for claiming pending main thread calls by moving them from
the datamanager async queue to their own.  Each worker thread queue also
represents spots for claiming and performing pending thread calls.

Set Up
======

By default, zc.async expects to have an object in the root of
the ZODB, alongside the application object, with a key of
'zc.async.datamanager'.  The package includes subscribers to
zope.app.appsetup.interfaces.IDatabaseOpenedEvent that sets an instance
up in this location if one does not exist [#subscribers]_.

Let's assume we have a reference to a database named `db`, a connection
named `conn`, a `root`, an application in the 'app' key [#setup]_, and a
handler named `installerAndNotifier` [#handlers]_.  If we provide a
handler, fire the event and examine the root, we will see the new
datamanager.

    >>> import zope.component
    >>> import zc.async.subscribers
    >>> zope.component.provideHandler(installerAndNotifier) # see footnotes
    ... # for explanation of where installerAndNotifier came from, and what
    ... # it is.
    >>> import zope.event
    >>> import zope.app.appsetup.interfaces
    >>> zope.event.notify(zope.app.appsetup.interfaces.DatabaseOpened(db))
    >>> import transaction
    >>> t = transaction.begin()
    >>> root['zc.async.datamanager'] # doctest: +ELLIPSIS
    <zc.async.datamanager.DataManager object at ...>

The default adapter from persistent object to datamanager will get us
the same result; adapting a persistent object to IDataManager is the
preferred spelling.

    >>> import zc.async.adapters
    >>> zope.component.provideAdapter(
    ...     zc.async.adapters.defaultDataManagerAdapter)
    >>> import zc.async.interfaces
    >>> zc.async.interfaces.IDataManager(app) # doctest: +ELLIPSIS
    <zc.async.datamanager.DataManager object at ...>

Normally, each process discovers or creates its UUID, and starts an
engine to do work.  The engine is a non-persistent object that
participates in the Twisted main loop.  It discovers or creates the
persistent worker object associated with the instance UUID in the
datamanager's `workers` mapping, and starts polling.  This would have
happened when the data manager was announced as available in the
InstallerAndNotifier above.

    >>> from zope.component import eventtesting
    >>> evs = eventtesting.getEvents(
    ...     zc.async.interfaces.IDataManagerAvailableEvent)
    >>> evs # doctest: +ELLIPSIS
    [<zc.async.interfaces.DataManagerAvailable object at ...>]

So now we would have had a subscriber that installed the worker in the
data manager.  But right now there are no workers, just because we
didn't want to talk about the next step yet.

    >>> len(zc.async.interfaces.IDataManager(app).workers)
    0

Let's install the subscriber we need and refire the event.  Our worker
will have a UUID created for it, and then it will be installed with the
UUID as key.  We can't actually use the same event because it has an
object from a different connection, so we'll recreate it.  We'll then use
a magic `time_passes` function to simulate the Twisted reactor cycling and
firing scheduled calls.  After we sync our connection with the database,
the worker appears.  It is tied to the engineUUID of the current engine.

    >>> zope.component.provideHandler(
    ...     zc.async.subscribers.installTwistedEngine)
    >>> zope.event.notify(
    ...     zc.async.interfaces.DataManagerAvailable(
    ...         root['zc.async.datamanager']))
    >>> time_passes()
    True
    >>> t = transaction.begin() # sync
    >>> len(zc.async.interfaces.IDataManager(app).workers)
    1
    >>> zc.async.interfaces.IDataManager(app).workers.values()[0]
    ... # doctest: +ELLIPSIS
    <zc.async.datamanager.Worker object at ...>
    >>> (zc.async.interfaces.IDataManager(app).workers.values()[0].engineUUID
    ...  is not None)
    True

The instance UUID, in hex, is stored in INSTANCE_HOME/etc/uuid.txt

    >>> import uuid
    >>> import os
    >>> f = open(os.path.join(
    ...     os.environ.get("INSTANCE_HOME"), 'etc', 'uuid.txt'))
    >>> uuid_hex = f.readline().strip()
    >>> f.close()
    >>> uuid = uuid.UUID(uuid_hex)
    >>> worker = zc.async.interfaces.IDataManager(app).workers[uuid]
    >>> worker.UUID == uuid
    True

The file is intended to stay in the instance home as a persistent identifier
of this particular worker.

Our worker has `thread` and `reactor` jobs, with all jobs available.  By
default, a worker begins offering a single thread job and a four
"simultaneous" reactor jobs.  This can be changed simply by changing the value
on the worker and committing.

    >>> worker.thread.size
    1
    >>> worker.reactor.size
    4
    >>> len(worker.thread)
    0
    >>> len(worker.reactor)
    0

But what are `thread` and `reactor` jobs?

A `thread` job is one that is performed in a thread with a dedicated
ZODB connection.  It's the simplest to use for typical tasks.

A thread job also may be overkill for some jobs that don't need a
connection constantly.  It also is not friendly to Twisted services. 

A `reactor` job is performed in the main thread, in a call scheduled by
the Twisted reactor.  It has some gotchas (see zc.twist's README), but it
can be good for jobs that don't need a constant connection, and for jobs
that can leverage Twisted code.

We now have a simple set up: a data manager with a single worker.  Let's start
making some asynchronous calls!

Basic Usage: IManager.add
=========================

The simplest case is simple to perform: pass a persistable callable to the
`put` method of one of the manager's queues.  We'll make reactor calls first.

    >>> from zc.async import interfaces
    >>> dm = zc.async.interfaces.IDataManager(app)
    >>> def send_message():
    ...     print "imagine this sent a message to another machine"
    >>> partial = dm.reactor.put(send_message)
    >>> transaction.commit()

Now a few cycles need to pass in order to have the job performed.  We'll
use a helper function called `time_flies` to simulate the asynchronous
cycles necessary for the manager and workers to perform the task.

    >>> dm.workers.values()[0].poll_seconds
    5
    >>> count = time_flies(5)
    imagine this sent a message to another machine

We also could have used the method of a persistent object.  Here's another
quick example.

    >>> import persistent
    >>> class Demo(persistent.Persistent):
    ...     counter = 0
    ...     def increase(self, value=1):
    ...         self.counter += value
    ...
    >>> app['demo'] = Demo()
    >>> transaction.commit()
    >>> app['demo'].counter
    0
    >>> partial = dm.reactor.put(app['demo'].increase)
    >>> transaction.commit()
    >>> count = time_flies(5)

We need to sync our connection so that we get the changes in other
connections: we can do that with a transaction begin, commit, or abort.

    >>> app['demo'].counter
    0
    >>> t = transaction.begin()
    >>> app['demo'].counter
    1

The method was called, and the persistent object modified!

You can also pass a timezone-aware datetime.datetime to schedule a
call.  The safest thing to use is a UTC timezone.

    >>> t = transaction.begin()
    >>> import datetime
    >>> import pytz
    >>> datetime.datetime.now(pytz.UTC)
    datetime.datetime(2006, 8, 10, 15, 44, 32, 211, tzinfo=<UTC>)
    >>> partial = dm.reactor.put(
    ...     send_message, datetime.datetime(
    ...         2006, 8, 10, 15, 45, tzinfo=pytz.UTC))
    >>> partial.begin_after
    datetime.datetime(2006, 8, 10, 15, 45, tzinfo=<UTC>)
    >>> transaction.commit()
    >>> count = time_flies(10)
    >>> count = time_flies(10)
    >>> count = time_flies(5)
    >>> count = time_flies(5)
    imagine this sent a message to another machine
    >>> datetime.datetime.now(pytz.UTC)
    datetime.datetime(2006, 8, 10, 15, 45, 2, 211, tzinfo=<UTC>)

If you set a time that has already passed, it will be run as if it had
been set to run immediately.

    >>> t = transaction.begin()
    >>> partial = dm.reactor.put(
    ...     send_message, datetime.datetime(2006, 7, 21, 12, tzinfo=pytz.UTC))
    >>> transaction.commit()
    >>> count = time_flies(5)
    imagine this sent a message to another machine

The `put` method of the thread and reactor queues is the manager's
entire application API.  Other methods are used to introspect, but are
not needed for basic usage.

But what is that result of the `put` call in the examples above?  A
partial?  What do you do with that?

Partials
========

The result of a call to `put` returns an IDataManagerPartial.  The
partial represents the pending call.  This object has a lot of
functionality that's explored in other documents in this package, and
demostrated a bit below, but here's a summary.  

- You can introspect it to look at, and even modify, the call and its
  arguments.

- You can specify that the partial may or may not be run by given
  workers (identifying them by their UUID).

- You can specify other calls that should be made on the basis of the
  result of this call.

- You can persist a reference to it, and periodically (after syncing
  your connection with the database, which happens whenever you begin or
  commit a transaction) check its `state` to see if it is equal to
  zc.async.interfaces.COMPLETED.  When it is, the call has run to
  completion, either to success or an exception.

- You can look at the result of the call (once COMPLETED).  It might be
  the result you expect, or a twisted.python.failure.Failure, which is a
  way to safely communicate exceptions across connections and machines
  and processes.

What's more, you can pass a Partial to the `put` call.  This means that
you aren't constrained to simply having simple non-argument calls
performed asynchronously, but you can pass a partial with a call,
arguments, and keyword arguments.  Here's a quick example.  We'll use
the same demo object, and its increase method, as our example above, but
this time we'll include some arguments [#partial]_.

    >>> t = transaction.begin()
    >>> partial = dm.reactor.put(
    ...     zc.async.partial.Partial(app['demo'].increase, 5))
    >>> transaction.commit()
    >>> count = time_flies(5)
    >>> t = transaction.begin()
    >>> app['demo'].counter
    6
    >>> partial = dm.reactor.put(
    ...     zc.async.partial.Partial(app['demo'].increase, value=10))
    >>> transaction.commit()
    >>> count = time_flies(5)
    >>> t = transaction.begin()
    >>> app['demo'].counter
    16

Thread Calls And Reactor Calls
==============================

...

Optimized Usage
===============

Writing a task that doesn't need a ZODB connection
--------------------------------------------------

...Twisted reactor tasks are best for this...

...also could have different IPartial implementation sets self as
ACTIVE, commits and closes connection, calls f with args, and when
result returns, gets connection again and sets value on it, changes
state, and performs callbacks, sets state...

Multiple ZEO workers
--------------------

...

Catching and Fixing Errors
==========================

...call installed during InstallTwistedWorker to check on worker...

...worker finds another process already installed with same UUID; could be
shutdown error (ghost of self) or really another process...show engineUUID...
some discussion already in datamanager.txt...

Gotchas
=======

...some callbacks may still be working when partial is completed.  Therefore
partial put in `completed` for worker so that it can have a chance to run to
completion (in addition to other goals, like being able to look at 

Patterns
========

Partials That Need a Certain Environment
----------------------------------------

...Partial that needs a certain environment: wrap partial in partial.  Outer
partial is responsible for checking if environment is good; if so, run inner
partial, and if not, create a new outer partial, copy over our excluded worker
UUIDs, add this worker UUID, set perform_after to adjusted value,
and schedule it...

Callbacks That Want to be Performed by a Worker
-----------------------------------------------

Callbacks are called immediately, whether they be within the call to the
partial, or within the `addCallbacks` call.  If you want the job to be done
asynchronously, make the callback with a partial.  The partial will get
a reference to the data_manager used by the main partial.  It can create a
partial, assign it to one of the data manager queues, and return the partial.
Consider the following (we use a `resolve` function to let all of the pending
calls resolve before the example proceeds [#resolve]_).

    >>> def multiply(*args):
    ...     res = 1
    ...     for a in args:
    ...         res *= a
    ...     return res
    ...
    >>> def doCallbackWithPartial(partial, res):
    ...     p = zc.async.partial.Partial(multiply, 2, res)
    ...     zc.async.interfaces.IDataManager(partial).thread.put(p)
    ...     return p
    ...
    >>> p = dm.thread.put(zc.async.partial.Partial(multiply, 3, 4))
    >>> p_callback = p.addCallbacks(
    ...     zc.async.partial.Partial.bind(doCallbackWithPartial))
    >>> transaction.commit()
    >>> resolve(p_callback)
    >>> p.result
    12
    >>> p.state == zc.async.interfaces.COMPLETED
    True
    >>> p_callback.state == zc.async.interfaces.COMPLETED
    True
    >>> p_callback.result
    24

Progress Reports
----------------

Using zc.twist.Partial, or by managing your own connections
otherwise, you can send messages back during a long-running connection. 
For instance, imagine you wanted to annotate a partial with progress
messages, while not actually committing the main work.

Here's an example of one way of getting this to work.  We can use the partial's
annotations, which are not touched by the partial code and are a separate
persistent object, so can be changed concurrently without conflict errors.

We'll run the partial within a threaded worker. The callable could use
twisted.internet.reactor.callFromThread to get the change to be made. 
Parts of the twist.Partial machinery expect to be called in the main
thread, where the twisted reactor is running.

    >>> import twisted.internet.reactor
    >>> def setAnnotation(partial, annotation_key, value):
    ...     partial.annotations[annotation_key] = value
    ...
    >>> import threading
    >>> import sys
    >>> thread_lock = threading.Lock()
    >>> main_lock = threading.Lock()
    >>> acquired = thread_lock.acquire()
    >>> acquired = main_lock.acquire()
    >>> def callWithProgressReport(partial):
    ...     print "do some work"
    ...     print "more work"
    ...     print "about half done"
    ...     twisted.internet.reactor.callFromThread(zc.twist.Partial(
    ...         setAnnotation, partial, 'zc.async.partial_txt.half_done', True))
    ...     main_lock.release()
    ...     acquired = thread_lock.acquire()
    ...     return 42
    ...
    >>> p = dm.thread.put(zc.async.partial.Partial.bind(callWithProgressReport))
    >>> transaction.commit()
    >>> ignore = time_flies(5); acquired = main_lock.acquire()
    ... # get the reactor to kick for main call; then wait for lock release.
    do some work
    more work
    about half done
    >>> ignore = time_flies(5) # get the reactor to kick for progress report
    >>> t = transaction.begin() # sync
    >>> p.annotations.get('zc.async.partial_txt.half_done')
    True
    >>> p.state == zc.async.interfaces.ACTIVE
    True
    >>> thread_lock.release()
    >>> resolve(p)
    >>> p.result
    42
    >>> thread_lock.release()
    >>> main_lock.release()

Expiration
----------

If you want your call to expire after a certain amount of time, keep
track of time yourself, and return a failure if you go over.  The
partial does not offer special support for this use case.

Stopping the Engine
-------------------

The subscriber that sets up the async engine within the Twisted reactor also
sets up a tearDown trigger.  We can look in our faux reactor and get it.

    >>> len(faux.triggers)
    1
    >>> len(faux.triggers[0])
    3
    >>> faux.triggers[0][:2]
    ('before', 'shutdown')
    >>> dm.workers.values()[0].engineUUID is not None
    True
    >>> d = faux.triggers[0][2]()
    >>> t = transaction.begin()
    >>> dm.workers.values()[0].engineUUID is None
    True

[#tear_down]_

=========
Footnotes
=========

.. [#uuid] UUIDs are generated by http://zesty.ca/python/uuid.html, as
    incorporated in Python 2.5.  They are expected to be found in 
    os.path.join(os.environ.get("INSTANCE_HOME"), 'etc', 'uuid.txt');
    this file will be created and populated with a new UUID if it does
    not exist.

.. [#subscribers] The zc.async.subscribers module provides two different
    subscribers to set up a datamanager.  One subscriber expects to put
    the object in the same database as the main application
    (`zc.async.subscribers.basicInstallerAndNotifier`).  This is the
    default, and should probably be used if you are a casual user.
    
    The other subscriber expects to put the object in a secondary
    database, with a reference to it in the main database
    (`zc.async.subscribers.installerAndNotifier`).  This approach keeps
    the database churn generated by zc.async, which can be significant,
    separate from your main data.  However, it also requires that you
    set up two databases in your zope.conf (or equivalent, if this is
    used outside of Zope 3).  And possibly even more onerously, it means
    that persistent objects used for calls must either already be
    committed, or be explicitly added to a connection; otherwise you
    will get an InvalidObjectReference (see
    cross-database-references.txt in the ZODB package).  The possible
    annoyances may be worth it to someone building a more demanding
    application.
    
    Again, the first subscriber is the easier to use, and is the default.
    You can use either one (or your own).

    If you do want to use the second subscriber, here's a start on what
    you might need to do in your zope.conf.  In a Zope without ZEO you
    would set something like this up.

    <zodb>
      <filestorage>
        path $DATADIR/Data.fs
      </filestorage>
    </zodb>
    <zodb zc.async>
      <filestorage>
        path $DATADIR/zc.async.fs
      </filestorage>
    </zodb>

    For ZEO, you could have the two databases on one server...
    
    <filestorage 1>
      path Data.fs
    </filestorage>
    <filestorage 2>
      path zc.async.fs
    </filestorage>
    
    ...and then set up ZEO clients something like this.
    
    <zodb>
      <zeoclient>
        server localhost:8100
        storage 1
        # ZEO client cache, in bytes
        cache-size 20MB
      </zeoclient>
    </zodb>
    <zodb zc.async>
      <zeoclient>
        server localhost:8100
        storage 2
        # ZEO client cache, in bytes
        cache-size 20MB
      </zeoclient>
    </zodb>

.. [#setup] This is a bit more than standard set-up code for a ZODB test,
    because it sets up a multi-database.

    >>> from zc.queue.tests import ConflictResolvingMappingStorage
    >>> from ZODB import DB
    >>> class Factory(object):
    ...     def __init__(self, name):
    ...         self.name = name
    ...     def open(self):
    ...         return DB(ConflictResolvingMappingStorage('test'))
    ...
    >>> import zope.app.appsetup.appsetup
    >>> db = zope.app.appsetup.appsetup.multi_database(
    ...     (Factory('main'), Factory('zc.async')))[0][0]
    >>> conn = db.open()
    >>> root = conn.root()
    >>> import zope.app.folder # import rootFolder
    >>> app = root['Application'] = zope.app.folder.rootFolder()
    >>> import transaction
    >>> transaction.commit()

    You must have two adapter registrations: IConnection to
    ITransactionManager, and IPersistent to IConnection.  We will also
    register IPersistent to ITransactionManager because the adapter is
    designed for it.

    >>> from zc.twist import transactionManager, connection
    >>> import zope.component
    >>> zope.component.provideAdapter(transactionManager)
    >>> zope.component.provideAdapter(connection)
    >>> import ZODB.interfaces
    >>> zope.component.provideAdapter(
    ...     transactionManager, adapts=(ZODB.interfaces.IConnection,))

    We need to be able to get data manager partials for functions and methods;
    normal partials for functions and methods; and a data manager for a partial.
    Here are the necessary registrations.

    >>> import zope.component
    >>> import types
    >>> import zc.async.interfaces
    >>> import zc.async.partial
    >>> import zc.async.adapters
    >>> zope.component.provideAdapter(
    ...     zc.async.adapters.method_to_datamanagerpartial)
    >>> zope.component.provideAdapter(
    ...     zc.async.adapters.function_to_datamanagerpartial)
    >>> zope.component.provideAdapter( # partial -> datamanagerpartial
    ...     zc.async.adapters.DataManagerPartial,
    ...     provides=zc.async.interfaces.IDataManagerPartial)
    >>> zope.component.provideAdapter(
    ...     zc.async.adapters.partial_to_datamanager)
    >>> zope.component.provideAdapter(
    ...     zc.async.partial.Partial,
    ...     adapts=(types.FunctionType,),
    ...     provides=zc.async.interfaces.IPartial)
    >>> zope.component.provideAdapter(
    ...     zc.async.partial.Partial,
    ...     adapts=(types.MethodType,),
    ...     provides=zc.async.interfaces.IPartial)
    ...
    
    A monkeypatch, removed in another footnote below.

    >>> import datetime
    >>> import pytz
    >>> old_datetime = datetime.datetime
    >>> def set_now(dt):
    ...     global _now
    ...     _now = _datetime(*dt.__reduce__()[1])
    ...
    >>> class _datetime(old_datetime):
    ...     @classmethod
    ...     def now(klass, tzinfo=None):
    ...         if tzinfo is None:
    ...             return _now.replace(tzinfo=None)
    ...         else:
    ...             return _now.astimezone(tzinfo)
    ...     def astimezone(self, tzinfo):
    ...         return _datetime(
    ...             *super(_datetime,self).astimezone(tzinfo).__reduce__()[1])
    ...     def replace(self, *args, **kwargs):
    ...         return _datetime(
    ...             *super(_datetime,self).replace(
    ...                 *args, **kwargs).__reduce__()[1])
    ...     def __repr__(self):
    ...         raw = super(_datetime, self).__repr__()
    ...         return "datetime.datetime%s" % (
    ...             raw[raw.index('('):],)
    ...     def __reduce__(self):
    ...         return (argh, super(_datetime, self).__reduce__()[1])
    >>> def argh(*args, **kwargs):
    ...     return _datetime(*args, **kwargs)
    ...
    >>> datetime.datetime = _datetime
    >>> _start = _now = datetime.datetime(
    ...     2006, 8, 10, 15, 44, 22, 211, pytz.UTC)

    We monkeypatch twisted.internet.reactor (and replace it below).  

    >>> import twisted.internet.reactor
    >>> import threading
    >>> import bisect
    >>> class FauxReactor(object):
    ...     def __init__(self):
    ...         self.time = 0
    ...         self.calls = []
    ...         self.triggers = []
    ...         self._lock = threading.Lock()
    ...     def callLater(self, delay, callable, *args, **kw):
    ...         res = (delay + self.time, callable, args, kw)
    ...         self._lock.acquire()
    ...         bisect.insort(self.calls, res)
    ...         self._lock.release()
    ...         # normally we're supposed to return something but not needed
    ...     def callFromThread(self, callable, *args, **kw):
    ...         self._lock.acquire()
    ...         bisect.insort(
    ...             self.calls,
    ...             (self.time, callable, args, kw))
    ...         self._lock.release()
    ...     def addSystemEventTrigger(self, *args):
    ...         self.triggers.append(args) # 'before', 'shutdown', callable
    ...     def _get_next(self, end):
    ...         self._lock.acquire()
    ...         try:
    ...             if self.calls and self.calls[0][0] <= end:
    ...                 return self.calls.pop(0)
    ...         finally:
    ...             self._lock.release()
    ...     def time_flies(self, time):
    ...         global _now
    ...         end = self.time + time
    ...         ct = 0
    ...         next = self._get_next(end)
    ...         while next is not None:
    ...             self.time, callable, args, kw = next
    ...             _now = _datetime(
    ...                 *(_start + datetime.timedelta(
    ...                     seconds=self.time)).__reduce__()[1])
    ...             callable(*args, **kw) # normally this would get try...except
    ...             ct += 1
    ...             next = self._get_next(end)
    ...         self.time = end
    ...         return ct
    ...     def time_passes(self):
    ...         next = self._get_next(self.time)
    ...         if next is not None:
    ...             self.time, callable, args, kw = next
    ...             callable(*args, **kw)
    ...             return True
    ...         return False
    ...
    >>> faux = FauxReactor()
    >>> oldCallLater = twisted.internet.reactor.callLater
    >>> oldCallFromThread = twisted.internet.reactor.callFromThread
    >>> oldAddSystemEventTrigger = (
    ...     twisted.internet.reactor.addSystemEventTrigger)
    >>> twisted.internet.reactor.callLater = faux.callLater
    >>> twisted.internet.reactor.callFromThread = faux.callFromThread
    >>> twisted.internet.reactor.addSystemEventTrigger = (
    ...     faux.addSystemEventTrigger)
    >>> time_flies = faux.time_flies
    >>> time_passes = faux.time_passes

.. [#handlers] In the second footnote above, the text describes two
    available subscribers.  When this documentation is run as a test, it
    is run twice, once with each.  To accomodate this, in our example
    below we appear to pull the "installerAndNotifier" out of the air:
    it is installed as a global when the test is run.

.. [#partial] The Partial class can take arguments and keyword arguments
    for the wrapped callable at call time as well, similar to Python
    2.5's `partial`.  This will be important when we use the Partial as
    a callback.  For this use case, though, realize that the partial
    will be called with no arguments, so you must supply all necessary
    arguments for the callable on creation time.

.. [#resolve]

    >>> import time
    >>> import ZODB.POSException
    >>> def resolve(p):
    ...     for i in range(100):
    ...         t = transaction.begin()
    ...         ignore = time_flies(5)
    ...         time.sleep(0)
    ...         t = transaction.begin()
    ...         try:
    ...             if (len(dm.thread) == 0 and
    ...                 len(dm.workers.values()[0].thread) == 0 and
    ...                 p.state == zc.async.interfaces.COMPLETED): 
    ...                 break
    ...         except ZODB.POSException.ReadConflictError:
    ...             pass
    ...     else:
    ...         print 'Timed out'

.. [#tear_down]

    >>> twisted.internet.reactor.callLater = oldCallLater
    >>> twisted.internet.reactor.callFromThread = oldCallFromThread
    >>> twisted.internet.reactor.addSystemEventTrigger = (
    ...     oldAddSystemEventTrigger)
    >>> datetime.datetime = old_datetime
    >>> import zc.async.engine
    >>> engine = zc.async.engine.engines[worker.UUID]
    >>> while 1: # make sure all the threads are dead before we close down
    ...     for t in engine._threads:
    ...         if t.isAlive():
    ...             break
    ...     else:
    ...         break
    ...
