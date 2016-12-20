import sys
import signal
import logging
import threading

from six.moves.queue import Queue

from fixtures import Fixture

from twisted.internet import reactor as defaultTwistedReactor
from twisted.internet.posixbase import _SIGCHLDWaker

from txfixtures._twisted.threading import (
    CallFromThreadTimeout,
    interruptableCallFromThread,
)

TIMEOUT = 5


class Reactor(Fixture):
    """A fixture to run the Twisted reactor in a separate thread.

    This fixture will spawn a new thread in the test process and run the
    Twisted reactor in it. Test code can then invoke asynchronous APIs
    by using :func:`~twisted.internet.threads.blockingCallFromThread`.
    """

    def __init__(self, reactor=None, timeout=TIMEOUT):
        """
        :param reactor: The Twisted reactor to run.
        :param timeout: Raise an exception if the reactor or the thread is
            it runs in doesn't start (at setUp time) or doesn't stop (at
            cleanUp time) in this amount of seconds.

        :ivar thread: The `~threading.Thread` that the reactor runs in.
        """
        super(Reactor, self).__init__()
        self.reactor = reactor or defaultTwistedReactor
        self.timeout = timeout
        self.thread = None

    def call(self, timeout, f, *a, **kw):
        """
        Convenience around `~twisted.internet.threads.blockingCallFromThread`,
        with timeout support.

        The function `f` will be invoked in the reactor's thread with the
        given arguments and keyword arguments. If `f` returns a Deferred, the
        calling code will block until it has fired.

        :return: The value returned by `f` or the value fired by the Deferred
            it returned. If `f` traces back or the Deferred it returned
            errbacks, the relevant exception will be propagated to the caller
            of this method.

        :raises CallFromThreadTimeout: If `timeout` seconds have
            elapsed and the Deferred returned by `f` hasn't fired yet.
        """
        return interruptableCallFromThread(self.reactor, timeout, f, *a, **kw)

    def reset(self):
        """Make sure that the reactor is still running.

        If the reactor and its thread have died, this method will try to
        recover them by creating a new thread and starting the reactor again.
        """

        if not self.thread.isAlive():
            # The thread died, let's try our best to recover.
            logging.warning("Twisted reactor thread died, trying to recover")
            self._stop()  # Resets the reactor in case it's in a broken state.
            self._start()
        else:
            # The thread is still running, make sure the reactor as well.
            self._assertReactorRunning()

    def _setUp(self):
        logging.info("Starting Twisted reactor in a separate thread")
        self._start()

    def _start(self):
        ready = Queue()  # Will be put None as soon as the reactor starts

        self.reactor.callWhenRunning(ready.put, None)
        self.thread = threading.Thread(
            target=self.reactor.run,
            # Don't let the reactor try to install signal handlers, since they
            # can only be installed from the main thread (we'll do it by hand
            # just below).
            kwargs=dict(installSignalHandlers=False),
        )
        self.addCleanup(self._stop)

        # Run in daemon mode. No matter what happens, when the test process
        # exists we don't want to hang waitng for the reactor thread to
        # terminate.
        self.thread.daemon = True

        self.thread.start()

        # Wait for the reactor to actually start and double check it's spinning
        ready.get(timeout=self.timeout)
        assert self.reactor.running, "Could not start the reactor"

        # Add the SIGCHLD waker as reactor reader. This needs to run in the
        # reactor thread as it's not thread-safe. The SIGCHLD waker will
        # react to SIGCHLD signals by writing to a dummy pipe, which will
        # wake up epoll() calls.
        self.call(1, self._addSIGCHLDWaker)

        # Install the actual signal hander (this needs to happen in the main
        # thread).
        self.reactor._childWaker.install()

        # Handle SIGINT (ctrl-c) and SIGTERM. This mimics the regular Twisted
        # code in _SignalReactorMixin._handleSignals (which can't be called
        # from a non-main thread).
        signal.signal(signal.SIGINT, self._handleSigInt)
        signal.signal(signal.SIGTERM, self._handleSigTerm)

        logging.info("Reactor started")

    def _stop(self):

        if self.thread.isAlive():
            # The thread is running, let's attempt a clean shutdown.
            logging.info("Stopping Twisted reactor and wait for its thread")

            # Assert that the reactor is still running, because, if not, it
            # means that it's basically hung, and there's nothing we can
            # do to stop it (we're in a different thread here).
            self._assertReactorRunning()

            # Use reactor.crash(), since calling reactor.stop() makes it
            # impossible to re-start it.
            try:
                self.call(self.timeout, self.reactor.crash)
            except CallFromThreadTimeout:
                raise RuntimeError("Could not stop the reactor")

            # The thread should exit almost immediately, try to wait a bit, and
            # fail if it doesn't.
            self.thread.join(timeout=self.timeout)
            if self.thread.isAlive():
                raise RuntimeError("Could not stop the reactor thread")

        elif self.reactor.running:
            # If the thread is dead but the reactor is still "running", it
            # probably means that the thread crashed badly, let's clean up
            # the reactor's state as much as we can and hope for the best.
            # It's thread-safe to invoke crash() from here since the reactor
            # thread isn't running anymore.
            logging.warning(
                "Twisted reactor has broken state, trying to reset it")
            self.reactor.crash()

        logging.info("Reactor stopped")

    def _assertReactorRunning(self):
        """Check if self.reactor is still running.

        This method is called by _stop() and _reset() in case the reactor's
        thread is still runnning. It will make sure that the reactor is still
        running as well, or raise an exception otherwise (since in that
        situation the thread is basically hung and there's nothing we can do
        for recovering).
        """
        if not self.reactor.running:
            raise RuntimeError("Hung reactor thread detected")

    def _addSIGCHLDWaker(self):
        """Add a `_SIGNCHLDWaker` to wake up the reactor when a child exits."""
        self.reactor._childWaker = _SIGCHLDWaker(self.reactor)
        self.reactor._internalReaders.add(self.reactor._childWaker)
        self.reactor.addReader(self.reactor._childWaker)

    # TODO: the signal handling code below is not tested, probably the best way
    #       would be to have an integration test that spawns a separate test
    #       process and send signals to it (using subunit.IsolatedTestCase?).

    def _handleSigInt(self, *args):  # pragma: no cover
        """
        Called when a SIGINT signal is received (for example user hit ctrl-c).
        """
        self.reactor.sigInt(*args)
        self._maybeFixReactorThreadRace()
        signal.default_int_handler()

    def _handleSigTerm(self, *args):  # pragma: no cover
        """
        Called when a SIGTERM signal is received.
        """
        self.reactor.sigTerm(*args)
        self._maybeFixReactorThreadRace()
        raise sys.exit(args[0])

    def _maybeFixReactorThreadRace(self):  # pragma: no cover
        # XXX For some obscure reason, this is needed in order to have the
        #     reactor properly wait for the shutdown sequence. It's probably
        #     a race between this thread and the reactor thread. Needs
        #     investigation.
        spin = Queue()
        self.reactor.callFromThread(self.reactor.callLater, 0, spin.put, None)
        spin.get(timeout=self.timeout)
