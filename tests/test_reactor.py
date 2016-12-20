import logging
import threading

from unittest import skipIf

from six import b
from six.moves.queue import Queue

from testtools import (
    TestCase,
    try_import,
)
from testtools.monkey import MonkeyPatcher

from fixtures import FakeLogger

from twisted.internet import reactor
from twisted.internet.utils import getProcessOutput

from txfixtures._twisted.threading import CallFromThreadTimeout

from txfixtures.reactor import Reactor

TIMEOUT = 5

asyncio = try_import("asyncio")

AsyncioSelectorReactor = try_import(
    "twisted.internet.asyncioreactor.AsyncioSelectorReactor")


class ReactorPatcher(MonkeyPatcher):
    """Monkey patch reactor methods to simulate various failure scenarios."""

    def __init__(self):
        super(ReactorPatcher, self).__init__()
        self._originalMainLoop = reactor.mainLoop
        self._originalCallFromThread = reactor.callFromThread

        self.add_patch(reactor, "mainLoop", self._mainLoop)
        self.add_patch(reactor, "callFromThread", self._callFromThread)

        self.crashingDo = None
        self.crashingNotify = None
        self.crashingAbruptly = False

        self.hangingDo = None

        self.callFromThreadTimeout = None

    def scheduleCrash(self, abruptly=False):
        """
        When the reactor is run, it will hang until a value is put into the
        `crashingDo` queue, and then crash.

        :param abruptly: If True, then crash badly by simply exiting the
            thread, without even calling reactor.crash().
        """
        self.crashingDo = Queue()
        self.crashingNotify = Queue()
        self.crashingAbruptly = abruptly
        return self.crashingDo

    def scheduleHang(self):
        """
        When the reactor is run, hang until a value is put into the
        `hangingDo` queue.
        """
        self.hangingDo = Queue()
        return self.hangingDo

    def scheduleCallFromThreadTimeout(self, function):
        """
        When the given function is called as argument via callFromThread, make
        it timeout.
        """
        self.callFromThreadTimeout = function

    def restore(self):
        """Restore the original reactor methods."""
        super(ReactorPatcher, self).restore()
        logging.info("Restoring reactor")
        if self.hangingDo:
            self.hangingDo.put(None)
        if self.crashingDo:
            self.crashingDo.put(None)
        reactor.crash()

    def _mainLoop(self):
        if self.hangingDo:
            self._waitAndHang()
            raise SystemExit(0)
        elif self.crashingDo:
            self._waitAndCrash()
            raise SystemExit(0)
        else:
            logging.info("Starting main loop")
            self._originalMainLoop()

    def _waitAndHang(self):
        logging.info("Hanging reactor")
        if self.crashingDo:
            self._waitAndCrash()
        logging.info("Waiting for hang queue")
        self.hangingDo.get(timeout=TIMEOUT)
        logging.info("Resuming hung main loop")
        self.hangingDo = None

    def _waitAndCrash(self):
        logging.info("Waiting for crash queue")
        self.crashingDo.get(timeout=TIMEOUT)
        abruptely = " abruptely" if self.crashingAbruptly else ""
        logging.info("Crashing main loop%s", abruptely)
        if not self.crashingAbruptly:
            reactor.crash()
        # Notify that we have successfully crashed
        self.crashingNotify.put(None)
        self.crashingDo = None

    def _callFromThread(self, f, *args, **kwargs):

        # We assume here that the only potential caller of the
        # reactor.callFromThread API is the interruptableCallFromThread
        # function defined in txfixtures._twisted.threading (since there's
        # no other direct or indirect use of reactor.callFromThread in the
        # code under test).
        #
        # The arguments that interruptableCallFromThread passes to
        # reactor.callFromThread are 2:
        #
        # - the queue to use for timing out the call
        # - the function to call in the main thread
        #
        # Here we check if the function argument matches the function that
        # we want to timeout.
        if args[1] == self.callFromThreadTimeout:
            logging.info("Trigger callFromThread timeout")

            def timeout(timeout=None):
                raise CallFromThreadTimeout()
            args[0].get = timeout
            return

        elif self.hangingDo or self.crashingDo:
            # Pretend we succeeded
            logging.info("Pretend callFromThread succeeded")
            args[0].put(None)
            return

        logging.info("Use original callFromThread")
        self._originalCallFromThread(f, *args, **kwargs)


class ReactorIntegrationTest(TestCase):

    def setUp(self):
        super(ReactorIntegrationTest, self).setUp()
        self.logger = self.useFixture(FakeLogger())
        self.patcher = ReactorPatcher()
        self.patcher.patch()
        self.fixture = Reactor()

        self.addCleanup(self._cleanup)

    def _cleanup(self):
        # Make sure that the thread has terminated and that the
        # reactor is back to a clean state.
        self.patcher.restore()
        if self.fixture.thread:
            logging.info("Waiting for thread to terminate")
            self.fixture.thread.join(timeout=TIMEOUT)
            assert not self.fixture.thread.isAlive(), "Thread did not stop"

    def test_reactor_running(self):
        """After setUp is run, the reactor is spinning."""
        self.useFixture(self.fixture)
        self.assertTrue(reactor.running)

    @skipIf(not AsyncioSelectorReactor, "asyncio reactor not available")
    def test_asyncio_reactor(self):
        """It's possible to start a custom reactor, like the asyncio one."""
        eventloop = asyncio.new_event_loop()
        self.fixture.reactor = AsyncioSelectorReactor(eventloop=eventloop)
        self.useFixture(self.fixture)
        self.assertTrue(self.fixture.reactor.running)

        # The asyncio loop is actually running
        ready = Queue()
        eventloop.call_soon_threadsafe(ready.put, None)
        self.assertIsNone(ready.get(timeout=TIMEOUT))

    def test_separate_thread(self):
        """The reactor runs in a separate thread."""
        self.useFixture(self.fixture)
        # Figure the number of active threads, excluding the twisted thread
        # pool.
        threads = []
        for thread in threading.enumerate():
            if thread.name.startswith("PoolThread-twisted.internet.reactor"):
                continue
            threads.append(thread)
        self.assertEqual(2, len(threads))

    def test_call(self):
        """The call() method is a convenience around blockingFromThread."""
        self.useFixture(self.fixture)
        output = self.fixture.call(TIMEOUT, getProcessOutput, b("uptime"))
        self.assertIn(b("load average"), output)

    def test_reset_thread_and_reactor_died(self):
        """
        The reset() method creates a new thread if the initial one has died.
        """
        self.useFixture(self.fixture)
        self.fixture.call(TIMEOUT, reactor.crash)
        self.fixture.thread.join(timeout=TIMEOUT)
        self.assertFalse(self.fixture.thread.isAlive())

        self.fixture.reset()
        self.assertTrue(reactor.running)
        self.assertIn(
            "Twisted reactor thread died, trying to recover",
            self.logger.output)

    def test_reset_thread_died_but_reactor_is_running(self):
        """
        If the reactor crashes badly and is left in a bad state (e.g. running),
        the fixtures tries a best-effort clean up.
        """
        self.patcher.scheduleCrash(abruptly=True)
        self.useFixture(self.fixture)
        self.patcher.crashingDo.put(None)

        # At this point the thread should be dead and the reactor broken
        self.fixture.thread.join(TIMEOUT)
        self.assertFalse(self.fixture.thread.isAlive())
        self.assertTrue(reactor.running)

        self.fixture.reset()

        self.assertIn(
            "Twisted reactor thread died, trying to recover",
            self.logger.output)
        self.assertIn(
            "Twisted reactor has broken state, trying to reset",
            self.logger.output)

        # Things should be back to normality
        self.assertTrue(self.fixture.thread.isAlive(), "Thread did not resume")
        self.assertTrue(reactor.running, "Reactor did not recover")

    def test_reset_thread_alive_but_reactor_is_not_running(self):
        """
        The reset() method bails out if the thread is alive but the reactor
        doesn't appear to be running.
        """
        self.patcher.scheduleHang()
        self.patcher.scheduleCrash()
        self.fixture.setUp()
        self.patcher.crashingDo.put(None)
        self.patcher.crashingNotify.get(timeout=TIMEOUT)

        # At this point the thread should be alive and the reactor broken
        self.assertTrue(self.fixture.thread.isAlive())
        self.assertFalse(reactor.running)

        error = self.assertRaises(RuntimeError, self.fixture.reset)
        self.assertEqual("Hung reactor thread detected", str(error))

    def test_cleanup_stops_thread_and_reactor(self):
        """After cleanUp is run, the reactor is stopped."""
        self.fixture.setUp()
        self.fixture.cleanUp()
        self.assertFalse(self.fixture.thread.isAlive())
        self.assertFalse(reactor.running)

    def test_cleanup_thread_not_alive(self):
        """
        If the thread is not alive, the cleanup phase is essentially a no-op.
        """
        self.fixture.setUp()
        self.fixture.call(TIMEOUT, reactor.crash)
        self.fixture.thread.join(TIMEOUT)
        self.fixture.cleanUp()

        # There's only the entry about starting the thread, since upon cleanup
        # nothing was running.
        self.assertNotIn(
            "Stopping Twisted reactor and wait for its thread",
            self.logger.output)
        self.assertNotIn(
            "Twisted reactor has broken state, trying to reset",
            self.logger.output)

    def test_cleanup_hung_thread(self):
        """
        If cleanUp() detects a hung thread with no reactor running, an error
        is raised.
        """
        self.patcher.scheduleHang()
        self.patcher.scheduleCrash()
        self.fixture.setUp()
        self.patcher.crashingDo.put(None)
        self.patcher.crashingNotify.get(timeout=TIMEOUT)

        # At this point the thread should be alive and the reactor stopped
        self.assertTrue(self.fixture.thread.isAlive())
        self.assertFalse(reactor.running)

        error = self.assertRaises(RuntimeError, self.fixture.cleanUp)
        self.assertEqual("Hung reactor thread detected", str(error))

    def test_cleanup_hung_reactor(self):
        """
        If cleanUp() can't stop the reactor, an error is raised.
        """
        self.patcher.scheduleHang()
        self.patcher.scheduleCallFromThreadTimeout(reactor.crash)
        self.fixture.setUp()

        # At this point the thread should be alive and the reactor running
        self.assertTrue(self.fixture.thread.isAlive())
        self.assertTrue(reactor.running)

        error = self.assertRaises(RuntimeError, self.fixture.cleanUp)
        self.assertEqual("Could not stop the reactor", str(error))
