from testtools import TestCase

from fixtures import FakeLogger

from systemfixtures import FakeThreads

from twisted.internet.defer import succeed
from twisted.internet.posixbase import _SIGCHLDWaker

from txfixtures._twisted.testing import ThreadedMemoryReactorClock

from txfixtures.reactor import Reactor


class ReactorTest(TestCase):

    def setUp(self):
        super(ReactorTest, self).setUp()
        self.logger = self.useFixture(FakeLogger())
        self.reactor = ThreadedMemoryReactorClock()
        self.fixture = Reactor(reactor=self.reactor, timeout=0)
        self.threads = self.useFixture(FakeThreads())

    def test_install_sigchld_waker(self):
        """
        At setup time, a reactor waker for the SIGCHLD signal is installed.
        """
        self.fixture.setUp()
        [reader] = list(self.reactor.readers)
        self.assertIsInstance(reader, _SIGCHLDWaker)
        self.assertTrue(reader.installed)

    def test_call(self):
        """The call() method is a convenience around blockingFromThread."""
        output = self.fixture.call(0, lambda: succeed("hello"))
        self.assertEqual("hello", output)

    def test_reset_thread_and_reactor_died(self):
        """
        The reset() method creates a new thread if the initial one has died.
        """
        self.fixture.setUp()
        self.fixture.reset()
        self.assertIn(
            "Twisted reactor thread died, trying to recover",
            self.logger.output)

    def test_reset_thread_died_but_reactor_is_running(self):
        """
        If the reactor crashes badly and is left in a bad state (e.g. running),
        the fixtures tries a best-effort clean up.
        """
        self.fixture.setUp()
        self.reactor.running = True
        self.fixture.reset()
        self.assertTrue(self.reactor.hasCrashed)
        self.assertIn(
            "Twisted reactor thread died, trying to recover",
            self.logger.output)
        self.assertIn(
            "Twisted reactor has broken state, trying to reset",
            self.logger.output)

    def test_reset_hung_thread(self):
        """
        The reset() method bails out if the thread is alive but the reactor
        doesn't appear to be running.
        """
        self.fixture.setUp()
        self.fixture.thread.alive = True
        self.reactor.running = False
        error = self.assertRaises(RuntimeError, self.fixture.reset)
        self.assertEqual("Hung reactor thread detected", str(error))

    def test_cleanup_stops_thread_and_reactor(self):
        """After cleanUp is run, the reactor is stopped."""
        self.fixture.setUp()
        self.fixture.cleanUp()
        self.assertFalse(self.fixture.thread.isAlive())
        self.assertFalse(self.fixture.reactor.running)

    def test_cleanup_thread_not_alive(self):
        """
        If the thread is not alive, the cleanup phase is essentially a no-op.
        """
        self.fixture.setUp()
        self.reactor.stop()
        self.fixture.thread.alive = False
        self.fixture.cleanUp()

        # There's only the entry about starting the thread, since upon cleanup
        # nothing was running.
        self.assertIn(
            "Starting Twisted reactor in a separate thread",
            self.logger.output)

    def test_cleanup_hung_thread(self):
        """
        If cleanUp() detects a hung thread with no reactor running, an error
        is raised.
        """
        self.fixture.setUp()
        self.fixture.thread.alive = True
        self.reactor.running = False
        error = self.assertRaises(RuntimeError, self.fixture.cleanUp)
        self.assertEqual("Hung reactor thread detected", str(error))

    def test_cleanup_hung_reactor(self):
        """
        If cleanUp() can't stop the reactor, an error is raised.
        """
        self.fixture.setUp()
        self.reactor.async = True
        self.fixture.thread.alive = True

        error = self.assertRaises(RuntimeError, self.fixture.cleanUp)
        self.assertEqual("Could not stop the reactor", str(error))

    def test_cleanup_thread_does_not_die(self):
        """
        If cleanUp() can't stop the thread, an error is raised.
        """
        self.fixture.setUp()

        self.fixture.thread.hang = True
        self.fixture.thread.alive = True

        error = self.assertRaises(RuntimeError, self.fixture.cleanUp)
        self.assertEqual("Could not stop the reactor thread", str(error))
