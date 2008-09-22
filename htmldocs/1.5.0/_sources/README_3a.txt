-----------------------------
Shared Single Database Set Up
-----------------------------

As described above, using a shared single database will probably be the
quickest way to get started.  Large-scale production usage will probably prefer
to use the :ref:`two-database-set-up` described later.

So, without further ado, here is the text of our zope.conf-alike, and of our
site.zcml-alike [#get_vals]_.

    >>> zope_conf = """
    ... site-definition %(site_zcml_file)s
    ...
    ... <zodb main>
    ...   <filestorage>
    ...     create true
    ...     path %(main_storage_path)s
    ...   </filestorage>
    ... </zodb>
    ...
    ... <product-config zc.z3monitor>
    ...   port %(monitor_port)s
    ... </product-config>
    ...
    ... <logger>
    ...   level debug
    ...   name zc.async
    ...   propagate no
    ...
    ...   <logfile>
    ...     path %(async_event_log)s
    ...   </logfile>
    ... </logger>
    ...
    ... <logger>
    ...   level debug
    ...   name zc.async.trace
    ...   propagate no
    ...
    ...   <logfile>
    ...     path %(async_trace_log)s
    ...   </logfile>
    ... </logger>
    ...
    ... <eventlog>
    ...   <logfile>
    ...     formatter zope.exceptions.log.Formatter
    ...     path STDOUT
    ...   </logfile>
    ...   <logfile>
    ...     formatter zope.exceptions.log.Formatter
    ...     path %(event_log)s
    ...   </logfile>
    ... </eventlog>
    ... """ % {'site_zcml_file': site_zcml_file,
    ...        'main_storage_path': os.path.join(dir, 'main.fs'),
    ...        'async_storage_path': os.path.join(dir, 'async.fs'),
    ...        'monitor_port': monitor_port,
    ...        'event_log': os.path.join(dir, 'z3.log'),
    ...        'async_event_log': os.path.join(dir, 'async.log'),
    ...        'async_trace_log': os.path.join(dir, 'async_trace.log'),}
    ...

In a non-trivial production system, you will also probably want to replace
the file storage with a <zeoclient> stanza.

Also note that an open monitor port should be behind a firewall, of course.

We'll assume that zdaemon.conf has been set up to put ZC_ASYNC_UUID in the
proper place too.  It would have looked something like this in the
zdaemon.conf::

    <environment>
      ZC_ASYNC_UUID /path/to/uuid.txt
    </environment>

(Other tools, such as supervisor, also can work, of course; their spellings are
different and are "left as an exercise to the reader" at the moment.)

We'll do that by hand:

    >>> os.environ['ZC_ASYNC_UUID'] = os.path.join(dir, 'uuid.txt')

Now let's define our site-zcml-alike.

    >>> site_zcml = """
    ... <configure xmlns='http://namespaces.zope.org/zope'
    ...            xmlns:meta="http://namespaces.zope.org/meta"
    ...            >
    ... <include package="zope.component" file="meta.zcml" />
    ... <include package="zope.component" />
    ... <include package="zc.z3monitor" />
    ... <include package="zc.async" file="basic_dispatcher_policy.zcml" />
    ...
    ... <!-- this is usually handled in Zope applications by the
    ...      zope.app.keyreference.persistent.connectionOfPersistent adapter -->
    ... <adapter factory="zc.twist.connection" />
    ... </configure>
    ... """

Now we're done.

If we process these files, and wait for a poll, we've got a working
set up [#process]_.

    >>> import zc.async.dispatcher
    >>> dispatcher = zc.async.dispatcher.get()
    >>> import pprint
    >>> pprint.pprint(get_poll(dispatcher, 0))
    {'': {'main': {'active jobs': [],
                   'error': None,
                   'len': 0,
                   'new jobs': [],
                   'size': 3}}}
    >>> bool(dispatcher.activated)
    True

We can ask for a job to be performed, and get the result.

    >>> conn = db.open()
    >>> root = conn.root()
    >>> import zc.async.interfaces
    >>> queue = zc.async.interfaces.IQueue(root)
    >>> import operator
    >>> import zc.async.job
    >>> job = queue.put(zc.async.job.Job(operator.mul, 21, 2))
    >>> import transaction
    >>> transaction.commit()
    >>> wait_for_result(job)
    42

We can connect to the monitor server with telnet.

    >>> import telnetlib
    >>> tn = telnetlib.Telnet('127.0.0.1', monitor_port)
    >>> tn.write('async status\n') # immediately disconnects
    >>> print tn.read_all() # doctest: +ELLIPSIS +NORMALIZE_WHITESPACE
    {
        "poll interval": {
            "seconds": ...
        },
        "status": "RUNNING",
        "time since last poll": {
            "seconds": ...
        },
        "uptime": {
            "seconds": ...
        },
        "uuid": "..."
    }
    <BLANKLINE>

Now we'll "shut down" with a CTRL-C, or SIGINT, and clean up.

    >>> import signal
    >>> if getattr(os, 'getpid', None) is not None: # UNIXEN, not Windows
    ...     pid = os.getpid()
    ...     try:
    ...         os.kill(pid, signal.SIGINT)
    ...     except KeyboardInterrupt:
    ...         if dispatcher.activated:
    ...             assert False, 'dispatcher did not deactivate'
    ...     else:
    ...         print "failed to send SIGINT, or something"
    ... else:
    ...     dispatcher.reactor.callFromThread(dispatcher.reactor.stop)
    ...     for i in range(30):
    ...         if not dispatcher.activated:
    ...             break
    ...         time.sleep(0.1)
    ...     else:
    ...         assert False, 'dispatcher did not deactivate'
    ...
    >>> import transaction
    >>> t = transaction.begin() # sync
    >>> import zope.component
    >>> import zc.async.interfaces
    >>> uuid = zope.component.getUtility(zc.async.interfaces.IUUID)
    >>> da = queue.dispatchers[uuid]
    >>> bool(da.activated)
    False

    >>> db.close()
    >>> import shutil
    >>> shutil.rmtree(dir)

These instructions are very similar to the :ref:`two-database-set-up`.

.. rubric:: Footnotes

.. [#get_vals]

    >>> import errno, os, random, socket, tempfile
    >>> dir = tempfile.mkdtemp()
    >>> site_zcml_file = os.path.join(dir, 'site.zcml')

    >>> s = socket.socket()
    >>> for i in range(20):
    ...     monitor_port = random.randint(20000, 49151)
    ...     try:
    ...         s.bind(('127.0.0.1', monitor_port))
    ...     except socket.error, e:
    ...         if e.args[0] == errno.EADDRINUSE:
    ...             pass
    ...         else:
    ...             raise
    ...     else:
    ...         s.close()
    ...         break
    ... else:
    ...     assert False, 'could not find available port'
    ...     monitor_port = None
    ...

.. [#process]

    >>> zope_conf_file = os.path.join(dir, 'zope.conf')
    >>> f = open(zope_conf_file, 'w')
    >>> f.write(zope_conf)
    >>> f.close()
    >>> f = open(site_zcml_file, 'w')
    >>> f.write(site_zcml)
    >>> f.close()

    >>> import zdaemon.zdoptions
    >>> import zope.app.appsetup
    >>> options = zdaemon.zdoptions.ZDOptions()
    >>> options.schemadir = os.path.join(
    ...     os.path.dirname(os.path.abspath(zope.app.appsetup.__file__)),
    ...     'schema')
    >>> options.realize(['-C', zope_conf_file])
    >>> config = options.configroot

    >>> import zope.app.appsetup.product
    >>> zope.app.appsetup.product.setProductConfigurations(
    ...     config.product_config)
    >>> ignore = zope.app.appsetup.config(config.site_definition)
    >>> import zope.app.appsetup.appsetup
    >>> db = zope.app.appsetup.appsetup.multi_database(config.databases)[0][0]

    >>> import zope.event
    >>> import zc.async.interfaces
    >>> zope.event.notify(zc.async.interfaces.DatabaseOpened(db))

    >>> from zc.async.testing import get_poll, wait_for_result
