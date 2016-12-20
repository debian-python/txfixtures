import logging

from datetime import datetime

from logging.handlers import BufferingHandler

from testtools import TestCase
from testtools.matchers import (
    Is,
    IsInstance,
    MatchesStructure,
)
from testtools.twistedsupport import (
    succeeded,
    failed,
    has_no_result,
)

from fixtures import (
    FakeLogger,
    LogHandler,
    MultipleExceptions,
)

from twisted.python.failure import Failure
from twisted.internet.error import (
    ProcessTerminated,
    ConnectionRefusedError,
)
from twisted.internet.defer import (
    Deferred,
    CancelledError,
    TimeoutError,
)
from twisted.test.proto_helpers import (
    StringTransport,
    MemoryReactorClock,
)

from txfixtures._twisted.testing import (
    ThreadedMemoryReactorClock,
    MemoryProcess,
)

from txfixtures.service import (
    Service,
    ServiceProtocol,
    ServiceOutputParser,
)


class ServiceTest(TestCase):

    def setUp(self):
        super(ServiceTest, self).setUp()
        self.logger = self.useFixture(FakeLogger())
        self.reactor = ThreadedMemoryReactorClock()
        self.fixture = Service(["foo"], reactor=self.reactor)

    def test_setup_start_process(self):
        """
        The fixture spawns the given process at setup time, the waits for it
        to be started.
        """
        self.fixture.setUp()
        self.assertEqual(["foo"], self.reactor.process.args)
        self.assertIn("Service process ready", self.logger.output)

    def test_expect_output(self):
        """
        It's possible to specify a string that should match the service's
        standard output, before the service is considered ready and setup
        completes.
        """
        self.reactor.process.data = b"hi\n"
        self.fixture.expectOutput("hi")
        self.fixture.setUp()
        self.assertIn("Service process emitted 'hi'", self.logger.output)

    def test_expect_output_timeout(self):
        """
        If the expected out is not received within the given timeout, an error
        is raised.
        """
        self.fixture.expectOutput("hi")
        error = self.assertRaises(MultipleExceptions, self.fixture.setUp)
        self.assertIs(error.args[0][0], TimeoutError)
        self.assertNotIn("Service process ready", self.logger.output)

    def test_cleanup_stop_process(self):
        """
        The fixture stops the given process at cleanup time, then waits for it
        to terminate.
        """
        self.fixture.setUp()
        self.fixture.cleanUp()
        self.assertIn("Service process reaped", self.logger.output)

    def test_set_output_format(self):
        """
        It's possible to specify an output format to, that will be used to
        generate a regular expression for parsing the service's output and
        emit the relevant logging record.
        """
        records = []
        logging.getLogger().handlers[0].handle = records.append

        self.reactor.process.data = b"2016-11-14 08:59:41.400 INFO my-app hi\n"
        fmt = "{Y}-{m}-{d} {H}:{M}:{S}.{msecs} {levelname} {name} {message}"

        self.fixture.setOutputFormat(fmt)
        self.fixture.setUp()

        for record in records:
            if record.processName != "MainProcess":
                break

        self.assertEqual("foo", record.processName)
        self.assertEqual("INFO", record.levelname)
        self.assertEqual("my-app", record.name)
        self.assertEqual("hi", record.msg)

    def test_expect_port(self):
        """
        It's possible to specify a port that the service process should start
        listening to, before the it's considered ready and setup completes.
        """
        self.fixture.expectPort(666)
        self.fixture.setUp()
        self.assertIn("Service opened port 666", self.logger.output)

    def test_reset(self):
        """
        The reset() method is a no-op if the service is still running.
        """
        self.fixture.setUp()
        self.assertIsNone(self.fixture.reset())

    def test_reset_service_died(self):
        """
        The reset() method raises an error if the service died.
        """
        self.fixture.setUp()
        self.reactor.process.processEnded(Failure(Exception("boom")))
        error = self.assertRaises(RuntimeError, self.fixture.reset)
        self.assertEqual("Service died", str(error))


class ServiceProtocolTest(TestCase):

    def setUp(self):
        super(ServiceProtocolTest, self).setUp()
        self.logger = self.useFixture(FakeLogger())
        self.reactor = MemoryReactorClock()
        self.process = MemoryProcess()
        self.protocol = ServiceProtocol(reactor=self.reactor)
        self.process.proto = self.protocol

    def test_fork(self):
        """
        When the connection is made it means that we sucessfully forked
        the service process, so we start waiting a bit to see if it stays
        running or exits shortly.
        """
        self.protocol.makeConnection(self.process)

        [call1, call2] = self.reactor.getDelayedCalls()
        self.assertEqual(call1.time, self.protocol.minUptime)
        self.assertEqual(call2.time, self.protocol.timeout)
        self.assertIn("Service process spawned", self.logger.output)

    def test_min_uptime(self):
        """
        If the process stays running for at least minUptime seconds, the
        'ready' Deferred gets fired.
        """
        self.protocol.makeConnection(self.process)
        self.reactor.advance(0.1)
        self.assertThat(self.protocol.ready, succeeded(Is(None)))
        self.assertIn(
            "Service process alive for 0.1 seconds", self.logger.output)

    def test_expected_output(self):
        """
        If some expected output is required, the 'ready' deferred fires only
        when such output has been received.
        """
        self.protocol.expectedOutput = "hello"
        self.protocol.makeConnection(self.process)

        self.reactor.advance(self.protocol.minUptime)
        self.assertThat(self.protocol.ready, has_no_result())

        self.protocol.outReceived(b"hello world!\n")
        self.assertThat(self.protocol.ready, succeeded(Is(None)))
        self.assertIn("Service process emitted 'hello'", self.logger.output)

    def test_expected_port(self):
        """
        If some expected port is required, the 'ready' deferred fires only
        when such port has been opened.
        """
        self.protocol.expectedPort = 1234
        self.protocol.makeConnection(self.process)

        self.reactor.advance(self.protocol.minUptime)
        self.assertThat(self.protocol.ready, has_no_result())

        factory = self.reactor.tcpClients[0][2]
        factory.buildProtocol(None).connectionMade()
        self.assertThat(self.protocol.ready, succeeded(Is(None)))
        self.assertIn("Service opened port 1234", self.logger.output)

    def test_expected_port_probe_failed(self):
        """
        If probing for the expected port fails, the probe will be retried.
        """
        self.protocol.expectedPort = 1234
        self.protocol.makeConnection(self.process)

        self.reactor.advance(self.protocol.minUptime)
        self.assertThat(self.protocol.ready, has_no_result())

        factory = self.reactor.tcpClients[0][2]
        factory.clientConnectionFailed(None, ConnectionRefusedError())
        self.assertIn("Service port probe failed", self.logger.output)

        self.reactor.advance(0.1)
        factory = self.reactor.tcpClients[1][2]
        factory.buildProtocol(None).connectionMade()
        self.assertThat(self.protocol.ready, succeeded(Is(None)))
        self.assertIn("Service opened port 1234", self.logger.output)

    def test_process_dies_shortly_after_fork(self):
        """
        If the service process exists right after having been spawned (for
        example the executable was not found), the 'ready' Deferred fires
        with an errback.
        """
        self.protocol.makeConnection(self.process)

        error = ProcessTerminated(exitCode=1, signal=None)
        self.protocol.processExited(Failure(error))
        self.assertThat(
            self.protocol.ready, failed(MatchesStructure(value=Is(error))))

    def test_cancel_while_waiting_for_uptime(self):
        """
        If the 'ready' deferred gets cancelled while still waiting for the
        minumum uptime, a proper message is emitted.
        """
        self.protocol.makeConnection(self.process)
        self.protocol.ready.cancel()
        self.assertIn(
            "minimum uptime not yet elapsed", self.logger.output)
        self.assertThat(
            self.protocol.ready,
            failed(MatchesStructure(value=IsInstance(CancelledError))))

    def test_process_dies_while_waiting_expected_output(self):
        """
        If the service process exists while waiting for the expected output,
        the 'ready' Deferred fires with an errback.
        """
        self.protocol.expectedOutput = "hello"
        self.protocol.makeConnection(self.process)

        self.reactor.advance(self.protocol.minUptime)

        error = ProcessTerminated(exitCode=1, signal=None)
        self.protocol.processExited(Failure(error))
        self.assertThat(
            self.protocol.ready, failed(MatchesStructure(value=Is(error))))

        # Further input received on the file descriptor will be discarded
        self.protocol.ready = Deferred()  # pretend that we didn't get fired
        self.protocol.outReceived(b"hello world!\n")
        self.assertThat(self.protocol.ready, has_no_result())

    def test_timeout_while_waiting_expected_output(self):
        """
        If the timeout elapses while waiting for the expected output, the
        'ready' Deferred fires with an errback.
        """
        self.protocol.expectedOutput = "hello"
        self.protocol.makeConnection(self.process)

        self.reactor.advance(self.protocol.minUptime)
        self.reactor.advance(self.protocol.timeout)

        self.assertThat(
            self.protocol.ready,
            failed(MatchesStructure(value=IsInstance(TimeoutError))))
        self.assertIn(
            "expected output not yet received", self.logger.output)

    def test_process_dies_while_probing_port(self):
        """
        If the service process exists while waiting for the expected port to,
        be open, the 'ready' Deferred fires with an errback.
        """
        self.protocol.expectedPort = 1234
        self.protocol.makeConnection(self.process)

        self.reactor.advance(self.protocol.minUptime)

        error = ProcessTerminated(exitCode=1, signal=None)
        self.protocol.processExited(Failure(error))
        self.assertThat(
            self.protocol.ready, failed(MatchesStructure(value=Is(error))))

        # No further probe will happen
        self.reactor.advance(0.1)
        self.assertEqual(1, len(self.reactor.tcpClients))

    def test_timeout_while_probing_port(self):
        """
        If the service process doesn't listen to the expected port within the,
        timeout, 'ready' Deferred fires with an errback.
        """
        self.protocol.expectedPort = 1234
        self.protocol.makeConnection(self.process)

        self.reactor.advance(self.protocol.minUptime)
        self.reactor.advance(self.protocol.timeout)

        self.assertThat(
            self.protocol.ready,
            failed(MatchesStructure(value=IsInstance(TimeoutError))))
        self.assertIn(
            "expected port not yet open", self.logger.output)

    def test_cancel_ready(self):
        """
        If the `ready` deferred gets cancelled, the protocol will stop doing
        anything related to waiting for the service to be ready.
        """
        self.protocol.makeConnection(self.process)
        self.protocol.ready.cancel()
        self.assertThat(
            self.protocol.ready,
            failed(MatchesStructure(value=IsInstance(CancelledError))))
        self.assertEqual(0, len(self.reactor.getDelayedCalls()))

    def test_terminated(self):
        """
        When the process is fully terminated, the 'terminated' deferred gets
        fired.
        """
        self.protocol.makeConnection(self.process)
        self.reactor.advance(self.protocol.minUptime)
        self.protocol.transport.processEnded(0)
        self.assertThat(self.protocol.terminated, succeeded(Is(None)))


class ServiceOutputParserTest(TestCase):

    def setUp(self):
        super(ServiceOutputParserTest, self).setUp()
        self.transport = StringTransport()
        self.handler = BufferingHandler(2)
        self.useFixture(LogHandler(self.handler))
        self.parser = ServiceOutputParser("my-app")
        self.parser.makeConnection(self.transport)

    def test_full_match(self):
        """
        If a line matches the given pattern, a log record is created using
        the values extracted from the match dictionary.
        """
        self.parser.pattern = (
            "{Y}-{m}-{d} {H}:{M}:{S}.{msecs} {levelname} {name} {message}")
        line = b"2016-11-14 08:59:41.400 INFO logger hi\n"
        self.parser.dataReceived(line)
        [record] = self.handler.buffer

        self.assertEqual("INFO", record.levelname)
        self.assertEqual("logger", record.name)
        self.assertEqual("hi", record.msg)
        self.assertEqual(1479113981, record.created)
        self.assertEqual(400, record.msecs)
        self.assertEqual("my-app", record.processName)

    def test_partial_match(self):
        """
        If a line only partially matches the given pattern, missing record
        values will be left alone.
        """
        self.parser.pattern = "{Y}-{m}-{d}( {H}:{M}:{S})? {name} {message}"
        self.parser.dataReceived(b"2016-11-14 logger hi\n")
        [record] = self.handler.buffer

        self.assertEqual("NOTSET", record.levelname)
        self.assertEqual(0, record.levelno)
        self.assertEqual("logger", record.name)
        self.assertEqual("hi", record.msg)
        date = datetime.utcfromtimestamp(record.created)
        self.assertNotEqual(
            ("2016", "11", "14"), (date.year, date.month, date.day))

    def test_no_match(self):
        """
        If a line doesn't match the given pattern, a log record is created
        with a message that equals the whole line.
        """
        self.parser.pattern = "{Y}-{m}-{d} {H}:{M}:{S} {message}"
        self.parser.dataReceived(b"hello world!\n")
        [record] = self.handler.buffer
        self.assertEqual("NOTSET", record.levelname)
        self.assertEqual(0, record.levelno)
        self.assertIsNone(record.name)
        self.assertEqual("hello world!", record.msg)

    def test_truncated(self):
        """
        If a line exceeds `MAX_LENGTH`, it will be truncated.
        """
        self.parser.MAX_LENGTH = 5
        self.parser.dataReceived(b"hello world!\n")
        [record] = self.handler.buffer
        self.assertEqual("hello", record.msg)

    def test_when_line_contains(self):
        """
        It's possible to set a callback that will be fired when a line contains
        a certain text.
        """
        tokens = [None, None]
        self.parser.whenLineContains("hello", tokens.pop)
        self.parser.dataReceived(b"hello world!\n")
        self.assertEqual([None], tokens)

        # If a further match is found, the callback is *not* fired.
        self.parser.dataReceived(b"hello world!\n")
        self.assertEqual([None], tokens)
