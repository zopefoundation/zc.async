.. _two-database-set-up:

-------------------
Two Database Set Up
-------------------

Even though it is a bit more trouble to set up, large-scale production usage
will probably prefer to use this approach, over the shared single database
described above.

For our zope.conf, we only need one additional stanza to the one seen above::

    <zodb async>
      <filestorage>
        create true
        path REPLACE_THIS_WITH_PATH_TO_STORAGE
      </filestorage>
    </zodb>

(You would replace "REPLACE_THIS_WITH_PATH_TO_STORAGE" with the path to the
storage file.)

As before, you will probably prefer to use ZEO rather than FileStorage in
production.

The zdaemon.conf instructions are the same: set the ZC_ASYNC_UUID environment
variable properly in the zdaemon.conf file.

For our site.zcml, the only difference is that we use the
multidb_dispatcher_policy.zcml file rather than the
basic_dispatcher_policy.zcml file.

If you want to change policy, change "multidb_dispatcher_policy.zcml" to
"dispatcher.zcml" in the example above and register your replacement bits for
the policy in "multidb_dispatcher_policy.zcml".  You'll see that most of that
comes from code in subscribers.py, which can be adjusted easily.

If we process the files described above, and wait for a poll, we've got a
working set up [#process_multi]_.

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

As before, we can ask for a job to be performed, and get the result.

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

Hopefully zc.async will be an easy-to-configure, easy-to-use, and useful tool
for you! Good luck! [#shutdown]_

.. rubric:: Footnotes

.. [#process_multi]

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
    ... <zodb async>
    ...   <filestorage>
    ...     create true
    ...     path %(async_storage_path)s
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

    >>> os.environ['ZC_ASYNC_UUID'] = os.path.join(dir, 'uuid.txt')

    >>> site_zcml = """
    ... <configure xmlns='http://namespaces.zope.org/zope'
    ...            xmlns:meta="http://namespaces.zope.org/meta"
    ...            >
    ... <include package="zope.component" file="meta.zcml" />
    ... <include package="zope.component" />
    ... <include package="zc.z3monitor" />
    ... <include package="zc.async" file="multidb_dispatcher_policy.zcml" />
    ...
    ... <!-- this is usually handled in Zope applications by the
    ...      zope.app.keyreference.persistent.connectionOfPersistent adapter -->
    ... <adapter factory="zc.twist.connection" />
    ... </configure>
    ... """

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

.. [#shutdown]

    >>> import zc.async.dispatcher
    >>> dispatcher = zc.async.dispatcher.get()
    >>> dispatcher.reactor.callFromThread(dispatcher.reactor.stop)
    >>> dispatcher.thread.join(3)

    >>> db.close()
    >>> db.databases['async'].close()
    >>> import shutil
    >>> shutil.rmtree(dir)
