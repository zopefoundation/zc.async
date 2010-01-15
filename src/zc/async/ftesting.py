import logging
import signal
import sys
import transaction
import zope.component

import zc.async.dispatcher
import zc.async.subscribers
import zc.async.testing

# helper functions convenient for Zope 3 functional tests

# setUp's default parameter for log_file used to be sys.stdout.
# This could cause problems in tests, as Python evaluates default
# arguments once, but sys.stdout may change across tests.  Passing
# None for log_file is already used in order to signify no logging,
# so we use a marker instead.
_marker = object()

def setUp(
    connection=None,
    queue_installer=zc.async.subscribers.queue_installer,
    dispatcher_installer=zc.async.subscribers.ThreadedDispatcherInstaller(
        poll_interval=0.1),
    agent_installer=zc.async.subscribers.agent_installer,
    log_file=_marker, log_level=logging.CRITICAL):
    """Set up zc.async, as is needed for Zope 3 functional tests.
    """
    if connection is None:
        connection = sys._getframe(1).f_globals['getRootFolder']()._p_jar
    db = connection.db()
    zope.component.provideHandler(agent_installer)
    event = zc.async.interfaces.DatabaseOpened(db)

    queue_installer(event)
    dispatcher_installer(event)
    dispatcher = zc.async.dispatcher.get()
    zc.async.testing.get_poll(dispatcher, count=0)
    assert "" in zc.async.testing.get_poll(dispatcher)
    assert dispatcher.activated is not None
    if log_file is not None:
        if log_file is _marker:
            log_file = sys.stdout
        # this helps with debugging critical problems that happen in your
        # zc.async calls.  Of course, if your test
        # intentionally generates CRITICAL log messages, you may not want this;
        # pass ``log_file=None`` to setUp.
        # stashing this on the dispatcher is a hack, but at least we're doing
        # it on code from the same package.
        dispatcher._debug_handler = zc.async.testing.print_logs(
            log_file, log_level)

def tearDown():
    dispatcher = zc.async.dispatcher.get()
    if getattr(dispatcher, '_debug_handler', None) is not None:
        logger = logging.getLogger('zc.async')
        logger.removeHandler(dispatcher._debug_handler)
        del dispatcher._debug_handler
    zc.async.testing.tear_down_dispatcher(dispatcher)
    zc.async.dispatcher.clear()
    # Restore previous signal handlers
    zc.async.subscribers.restore_signal_handlers(dispatcher)
    # Avoid leaking file descriptors
    # (see http://twistedmatrix.com/trac/ticket/3063).
    dispatcher.reactor.removeReader(dispatcher.reactor.waker)
    dispatcher.reactor.waker.connectionLost(None)
