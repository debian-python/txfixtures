"""Extensions to Twisted's stock testing helpers."""

import signal

from twisted.test.proto_helpers import MemoryReactorClock
from twisted.internet.error import ProcessTerminated
from twisted.internet._baseprocess import BaseProcess
from twisted.python.failure import Failure

EXPECTED_SIGNALS = (signal.SIGTERM, signal.SIGTERM)


class ThreadedMemoryReactorClock(MemoryReactorClock):
    """Extend Twisted's test reactor with more reactor-level features.

    :ivar async: A flag indicating whether callFromThread calls should be
        executed synchronously as soon as callFromThread is called.
    """

    def __init__(self):
        super(ThreadedMemoryReactorClock, self).__init__()
        self.async = False
        self.process = MemoryProcess()
        self._internalReaders = set()

    def run(self, installSignalHandlers=False):
        super(ThreadedMemoryReactorClock, self).run()
        self.installSignalHandlers = installSignalHandlers
        self.running = True

    def crash(self):
        super(ThreadedMemoryReactorClock, self).crash()
        self.running = False

    def callFromThread(self, f, *args, **kwargs):
        if self.async:
            return
        f(*args, **kwargs)

        # Spin the timer until there are no delayed calls left, or until the
        # limit is reached.
        limit = 10
        count = 0
        while self.getDelayedCalls() and count < limit:
            call = self.getDelayedCalls()[0]
            self.advance(call.getTime() - self.seconds())
            count += 1

    def addReader(self, reader):
        reader.install = lambda: setattr(reader, "installed", True)
        super(ThreadedMemoryReactorClock, self).addReader(reader)

    def spawnProcess(self, processProtocol, executable, args=(), env={},
                     path=None, uid=None, gid=None, usePTY=0, childFDs=None):
        self.process.args = args
        self.process.proto = processProtocol
        self.process.pid = 123
        self.process.proto.makeConnection(self.process)
        if self.process.data is not None:
            self.process.proto.outReceived(self.process.data)
        return self.process

    def connectTCP(self, host, port, factory, timeout=30, bindAddress=None):
        protocol = factory.buildProtocol(None)
        protocol.connectionMade()


class MemoryProcess(BaseProcess):
    """Simulate a real :class:`~twisted.internet.process.Process`."""

    def __init__(self):
        super(MemoryProcess, self).__init__(None)
        self.signals = EXPECTED_SIGNALS
        self.signalled = True

        # These are expected by the base class
        self.data = None
        self.executable = None

    def signalProcess(self, signalID):
        assert signalID in self.signals, "Unexpected signal: %s" % signalID
        self.signalled = True
        self.pid = None
        self.processEnded(signalID)

    def _getReason(self, status):
        status = signal = None
        if self.signalled:
            signal = status
        return Failure(ProcessTerminated(status=status, signal=signal))
