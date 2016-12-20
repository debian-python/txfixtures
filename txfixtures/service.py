import logging
import os
import re
import signal
import socket
import logging

from datetime import datetime

from psutil import Process

from fixtures import Fixture

from twisted.internet import reactor as defaultTwistedReactor
from twisted.internet.protocol import (
    Factory,
    Protocol,
    ProcessProtocol,
)
from twisted.internet.defer import (
    Deferred,
    inlineCallbacks,
)
from twisted.internet.task import LoopingCall
from twisted.internet.endpoints import TCP4ClientEndpoint
from twisted.internet.error import (
    ConnectionRefusedError,
    ConnectingCancelledError,
)
from twisted.protocols.basic import LineOnlyReceiver

from txfixtures._twisted.threading import interruptableCallFromThread


TIMEOUT = 15

# Some processes (like mongodb) use an abbreviated code for level names. We
# keep a mapping for transparently convert between them and standard Python
# level names.
SHORT_LEVELS = {
    "C": "CRITICAL",
    "E": "ERROR",
    "W": "WARNING",
    "I": "INFO",
    "D": "DEBUG",
}


class Service(Fixture):
    """Spawn, control and monitor a background service."""

    def __init__(self, command, reactor=None, timeout=TIMEOUT, env=None):
        super(Service, self).__init__()
        self.command = command
        self.env = _encodeDictValues(env or os.environ.copy())
        parser = ServiceOutputParser(self._executable)

        # XXX Set the reactor as private, since the public 'reactor' attribute
        #     is typically a Reactor fixture, set by testresources as
        #     dependency.
        if reactor is None:
            reactor = defaultTwistedReactor
        self._reactor = reactor

        self.protocol = ServiceProtocol(
            reactor=self._reactor, parser=parser, timeout=timeout)

        self._eventTriggerID = None

    def reset(self):
        if self.protocol.terminated.called:
            raise RuntimeError("Service died")

    def expectOutput(self, data):
        self.protocol.expectedOutput = data

    def expectPort(self, port):
        self.protocol.expectedPort = port

    def setOutputFormat(self, outFormat):
        self.protocol.parser.pattern = outFormat

    def allocatePort(self):
        """Allocate an unused port.

        This method can be used by subclasses to allocate a random ports for
        the service they spawn.

        There is a small race condition here (between the time we allocate the
        port, and the time it actually gets used), but for the purposes for
        which this method gets used it isn't a problem in practice.
        """
        sock = socket.socket()
        try:
            sock.bind(("localhost", 0))
            _, port = sock.getsockname()
            return port
        finally:
            sock.close()

    def _setUp(self):
        logging.info("Spawning service process %s", self.command)
        self.addCleanup(self._stop)
        self._callFromThread(self._start)

    @property
    def _executable(self):
        return self.command[0]

    @property
    def _args(self):
        return self.command

    @property
    def _name(self):
        return os.path.basename(self._executable)

    @inlineCallbacks
    def _start(self):
        self._reactor.spawnProcess(
            self.protocol, self._executable, args=self._args, env=self.env)

        # This cleanup handler will be triggered in case of SIGTERM and SIGINT,
        # when the reactor will initiate an unexpected shutdown sequence.
        self._eventTriggerID = self._reactor.addSystemEventTrigger(
            "before", "shutdown", self._terminateProcess)

        yield self.protocol.ready

    def _stop(self):
        logging.info("Stopping service process %s", self.command)

        try:
            self._callFromThread(self._terminateProcess)
        except:
            if self.protocol.transport.pid:
                # In case something goes wrong let's try our best to not leave
                # running processes around.
                logging.info(
                    "Service process didn't terminate, trying to kill it")
                process = Process(self.protocol.transport.pid)
                process.kill()
                process.wait(timeout=1)

    def _callFromThread(self, f):
        # Set an additional timeout for the callFromThread call itself. We
        # want this timeout to be greater than the 'ready' deferred timeout
        # set in _start(), so if the reactor thread is hung or dies we still
        # properly timeout.
        timeout = self.protocol.timeout + 1
        interruptableCallFromThread(self._reactor, timeout, f)

    @inlineCallbacks
    def _terminateProcess(self):
        if self._eventTriggerID:
            # Clear the shutdown event trigger, since we're going to cleanup
            # normally.
            self._reactor.removeSystemEventTrigger(self._eventTriggerID)
        if self.protocol.transport.pid:
            logging.info("Sending SIGTERM to service process '%s'", self._name)
            self.protocol.transport.signalProcess(signal.SIGTERM)
            logging.info("Waiting for service process to terminate")
            yield self.protocol.terminated


class ServiceProtocol(ProcessProtocol):
    """Start and stop a background service process.

    This :class:`~twisted.internet.protocol.ProcessProtocol` manages the start
    up and termination phases of a background service process. The process is
    considered 'running' when it has stayed up for at least 0.1 seconds (or any
    other non default value which `minUptime` is set too), and optionally when
    it has emitted a certain string and/or it has started listening to a
    certain port.
    """

    #: The service process must stay up at least this amount of seconds, before
    #: it's considered running. This allows to catch common issues like the
    #: service process executable not being in PATH or not being executable.
    minUptime = 0.1

    def __init__(self, reactor=None, parser=None, timeout=TIMEOUT):
        self.reactor = reactor or defaultTwistedReactor
        self.parser = parser or ServiceOutputParser("")

        #: Maximum amount of seconds to wait for the service to be ready. After
        #: that, the 'ready' deferred will errback with a TimeoutError.
        self.timeout = timeout

        #: Optional text that we expect the process to emit in standard output
        #: before we consider it ready.
        self.expectedOutput = None

        #: Optional port number that we expect the service process to listen,
        #: before we consider it ready.
        self.expectedPort = None

        #: Deferred that will fire when the service is considered ready, i.e.
        #: it has stayed up for at least minUptime seconds, has produced the
        #: expected output (if any), and is listening to the expected port (if
        #: any). Upon cancellation, any waiting activity will be stopped.
        self.ready = Deferred(lambda _: self._stopWaitingForReady())

        #: Deferred that will fire when the service has fully terminated, i.e.
        #: it has exited and we parent process have read any outstanding data
        #: in the pipes and have closed them.
        self.terminated = Deferred()

        # Delayed call that gets started right after the process has been
        # spawned. Its purpose is to make the protocol "sleep" for a minUptime
        # seconds (typically 0.1 seconds): if the process exits before this
        # little time has elapsed, an error gets raised.
        self._minUptimeCall = None

        # Deferred that will be fired when the process emits the expected
        # output (if any).
        self._expectedOutputReady = Deferred()

        # A LoopingCall instance that will periodically try to open the port
        # that the process is supposed to start listening to.
        self._probePortLoop = None

        # A connector as returned by TCP4ClientEndpoint.connect() that can be
        # used to abort an ongoing connection attempt as performed by the
        # port probe loop.
        self._probePortAttempt = None

    def connectionMade(self):
        # Called (indirectly) by `spawnProcess` after the `os.fork` call has
        # succeeded.

        logging.info("Service process spawned")

        self.ready.addTimeout(self.timeout, self.reactor)

        # The twisted.protocols.basic.LineOnlyReceiver class expects to know
        # when the transport is disconnecting.
        self.disconnecting = False

        # Let's see if the process stays running for at least
        self._minUptimeCall = self.reactor.callLater(
            self.minUptime, self._minUptimeElapsed)

        if self.expectedOutput:
            # From this point on, be prepared to receive the expected output at
            # any time.
            self.parser.whenLineContains(
                self.expectedOutput, self._expectedOutputReceived)
        else:
            # There's no output we expect, so we fire this Deferred right away.
            # When _minUptimeElapsed will be called, the callback that gets
            # attached to this Deferred will fire synchronously.
            self._expectedOutputReady.callback(None)

        self.parser.makeConnection(self)

    def outReceived(self, data):
        # Called when we receive data from the standard output of the service.
        self.parser.dataReceived(data)

    errReceived = outReceived

    def processExited(self, reason):
        # Called when the service process exited.

        logging.info("Service process exited: %s", reason.getErrorMessage())

        # If we did not reach the 'ready' state yet, the let's fire the 'ready'
        # Deferred with an error.
        if not self.ready.called:
            self._stopWaitingForReady(reason)

    def processEnded(self, reason):
        # Called when the process has been reaped.
        logging.info("Service process reaped")
        self.terminated.callback(None)

    def _minUptimeElapsed(self):
        """
        Called if the process didn't exit in the first `minUptime` seconds
        after having been spawned.
        """
        logging.info("Service process alive for %.1f seconds", self.minUptime)

        # Now wait for the expected output and then start polling the port
        # we expect the service to listen to (if there's no expected output
        # and/or no expected port, these deferreds will fire synchronously).
        if self.expectedPort:
            self._expectedOutputReady.addCallback(self._startProbePortLoop)
        self._expectedOutputReady.addCallback(self._maybeFireReady)

    def _expectedOutputReceived(self):
        """
        Called after `_minUptimeElapsed` and the service process has emitted
        the expected output string.
        """
        # Let's fire the relevant deferred, so we can move forward to polling
        # the expected port, or declaring the service as ready (if there's no
        # expected port).
        logging.info("Service process emitted '%s'", self.expectedOutput)
        self._expectedOutputReady.callback(None)

    @inlineCallbacks
    def _startProbePortLoop(self, _):
        """
        Called when the service process has stayed up for at least `minUptime`
        seconds and it has emitted the expected output string (or there was no
        expected output string at all).
        """

        self._probePortLoop = LoopingCall(self._probePort)
        self._probePortLoop.clock = self.reactor

        # The LoopingCall.start() method returns a deferred that will fire
        # when the loop stops, i.e. when we successfully probe the port.
        yield self._probePortLoop.start(0.1)

    @inlineCallbacks
    def _probePort(self):
        """Perform a single attempt to connect to the expected port.

        If the probe succeeds the probe loop will be stoped.

        If the probe fails with a connection error, we'll just return
        gracefully (we'll be invoked again at the next loop iteration).
        """
        logging.info("Polling service port '%s'", self.expectedPort)

        endpoint = TCP4ClientEndpoint(
            self.reactor, "localhost", self.expectedPort)

        try:
            factory = Factory()
            factory.protocol = Protocol
            self._probePortAttempt = endpoint.connect(factory)
            yield self._probePortAttempt
        except ConnectionRefusedError as error:
            logging.info("Service port probe failed: %s", error)
        except ConnectingCancelledError as error:
            # This happens if _stopWaitingForReady gets called while we are
            # waiting for the enpoint connect() to succeed or fail.
            logging.info("Service port probe cancelled: %s", error)
        else:
            if self._probePortLoop.running:
                self._probePortLoop.stop()
                logging.info("Service opened port %d", self.expectedPort)
        finally:
            self._probePortAttempt = None

    def _maybeFireReady(self, result):
        """Fire the 'ready' deferred, unless we're aborting the startup.

        If the startup sequence is aborting (either because the `ready`
        deferred was cancelled by user code, or because the process died and
        `processExited` was called), this will just be a no-op, as we rely
        on the aborting code to errback the `ready` deferred.
        """
        if not self.disconnecting:
            logging.info("Service process ready")
            self.ready.callback(result)

    def _stopWaitingForReady(self, reason=None):
        """
        Stop any delayed call or activity associated with the initial waiting
        for the service to be ready.

        If `reason` is passed, the `ready` deferred will errback with the given
        failure.
        """
        # This will prevent the ServiceOutputParser protocol from firing any
        # further lineReceived event, so we don't fire _expectedOutputReady.
        #
        # It will also prevent _maybeFireReady from firing the 'ready'
        # deferred, since we want to do it ourselves with the given reason (if
        # any).
        self.disconnecting = True

        message = None

        if self._minUptimeCall.active():
            self._minUptimeCall.cancel()
            message = "minimum uptime not yet elapsed"

        elif self.expectedOutput and not self._expectedOutputReady.called:
            message = "expected output not yet received"

        elif self.expectedPort:
            if self._probePortAttempt:
                self._probePortAttempt.cancel()

            self._probePortLoop.stop()
            message = "expected port not yet open"

        # We can safely assume that one of the conditions above is holding,
        # because otherwise the 'ready' deferred would have already fired. In
        # any case let's put an explicit assertion here for good measure.
        assert message, "Unexpected protocol state while cancelling wait"

        logging.info(
            "Give up waiting for the service to be ready: %s", message)

        if reason:
            self.ready.callback(reason)


class ServiceOutputParser(LineOnlyReceiver):
    """
    Parse the standard output stream of a service and forward it to the Python
    logging system.

    The stream is assumed to be a UTF-8 sequence of lines each delimited by
    a (configurable) delimiter character.

    Each received line is tested against the RegEx pattern provided in the
    constructor. If a match is found, a :class:`~logging.LogRecord` is built
    using the information from the groups of the match object, otherwise
    default values will be used.

    The record is then passed to the :class:`~logging.Logger` provided in the
    constructor.

    Match objects that result from the RegEx pattern are supposed to provide
    groups named after the substitutions below.
    """

    #: The delimiter character identifying the end of a line.
    delimiter = b"\n"

    #: Substitutions for commonly used groups in line match patterns. For
    #: example, this allows you to use "{Y}-{m}-{S}" as pattern snippet, as
    #  opposed to an explicit "(?P<Y>\d{4})-(?P<m>\d{2})-(?P<d>\d{2})".
    substitutions = {
        "Y": "(?P<Y>\d{4})",
        "m": "(?P<m>\d{2})",
        "d": "(?P<d>\d{2})",
        "H": "(?P<H>\d{2})",
        "M": "(?P<M>\d{2})",
        "S": "(?P<S>\d{2})",
        "msecs": "(?P<msecs>\d{3})",
        "levelname": "(?P<levelname>[a-zA-Z]+)",
        "name": "(?P<name>.+)",
        "message": "(?P<message>.+)",
    }

    def __init__(self, service, logger=None, pattern=None):
        """
        :param service: A string identifying the service whose output is being
            parsed. It will be attached as 'service' attribute to all log
            records emitted.
        """
        self.service = service
        self.pattern = pattern or "{message}"
        self.logger = logger or logging.getLogger("")
        self._callbacks = {}

    def whenLineContains(self, text, callback):
        """Fire the given callback when a line contains the given text.

        The callback will be fired only once when and if a match is found.
        """
        self._callbacks[text] = callback

    def lineReceived(self, line):
        """Foward the received line to the Python logging system."""
        message = line.decode("utf-8")
        params = {
            "levelname": "NOTSET",
            "levelno": 0,
            "msg": message,
            "processName": self.service,
        }

        match = re.match(self.pattern.format(**self.substitutions), message)
        if match:
            params.update(self._getLogRecordParamsForMatch(match))

        record = logging.makeLogRecord(params)
        self.logger.handle(record)

        for text in list(self._callbacks.keys()):
            if text in record.msg:
                self._callbacks.pop(text)()

    def lineLengthExceeded(self, line):
        """Simply truncate the line."""
        self.lineReceived(line[:self.MAX_LENGTH])

    def _getLogRecordParamsForMatch(self, match):
        """
        Use the given `match` regex object to create a dict of parameters
        to be passed to `logging.makeLogRecord`.

        This method will try to use all the information extracted by the
        match. If some of it is missing or incomplete, it will be discarded.
        """
        groups = _filterNoneValues(match.groupdict())
        params = {
            "name": groups.get("name"),
            "msg": groups.get("message"),
        }

        if "levelname" in groups:
            levelname = groups["levelname"].upper()
            if len(levelname) == 1:
                levelname = SHORT_LEVELS.get(levelname, "INFO")
            params["levelname"] = levelname
            params["levelno"] = logging.getLevelName(params["levelname"])

        # Only set creation time if all date-related groups are there.
        if set(groups.keys()).issuperset({"Y", "m", "d", "H", "M", "S"}):
            params["created"] = float(datetime(
                int(groups["Y"]),
                int(groups["m"]),
                int(groups["d"]),
                int(groups["H"]),
                int(groups["M"]),
                int(groups["S"]),
            ).strftime("%s"))

        if "msecs" in groups:
            params["msecs"] = float(groups["msecs"])

        return params


def _filterNoneValues(d):
    """
    Return a dict which is the same as `d`, except for keys with None values,
    which get discarded.
    """
    return dict([(k, v) for k, v in d.items() if v is not None])


def _encodeDictValues(d):
    """
    Return a dict whose unicode values get UTF-8 encoded to bytes.
    """
    return dict(
        [(_maybeEncode(k), _maybeEncode(v))
        for k, v in d.items() if v is not None])


def _maybeEncode(x):
    """
    If x is a string, encode it to bytes using UTF-8.
    """
    if isinstance(x, str):
        x = x.encode("utf-8")
    return x
