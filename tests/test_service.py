import os
import signal
import socket

from testtools import TestCase
from testtools.twistedsupport import AsynchronousDeferredRunTest

from fixtures import (
    FakeLogger,
    MultipleExceptions,
    TempDir
)

from systemfixtures import FakeExecutable

from twisted.internet import reactor
from twisted.internet.defer import (
    TimeoutError,
    inlineCallbacks,
)
from twisted.internet.error import (
    ProcessTerminated,
    ProcessDone,
)

from txfixtures.reactor import Reactor
from txfixtures.service import (
    Service,
    ServiceProtocol,
)


class ServiceIntegrationTest(TestCase):

    def setUp(self):
        super(ServiceIntegrationTest, self).setUp()
        self.logger = self.useFixture(FakeLogger())
        self.useFixture(Reactor())
        self.script = self.useFixture(FakeExecutable())
        self.fixture = Service([self.script.path.encode("utf-8")], timeout=1)

    def test_service_ready(self):
        """After setUp is run, the service is fully ready."""
        self.script.out("hello")
        self.script.listen()
        self.script.sleep(2)
        self.fixture.expectOutput("hello")
        self.fixture.expectPort(self.script.port)
        self.useFixture(self.fixture)

    def test_unknown_command(self):
        """If an unknown command is given, setUp raises an error."""
        self.fixture.command = [b"/foobar"]
        error = self.assertRaises(MultipleExceptions, self.fixture.setUp)
        self.assertIsInstance(error.args[0][1], ProcessTerminated)
        self.assertIn("No such file or directory", self.logger.output)

    def test_non_executable_command(self):
        """If the given command is not executable, setUp raises an error."""
        executable = self.useFixture(TempDir()).join("foobar")
        with open(executable, "w") as fd:
            fd.write("")
        self.fixture.command = [executable.encode("utf-8")]
        self.fixture.minUptime = 0.5
        error = self.assertRaises(MultipleExceptions, self.fixture.setUp)
        self.assertIsInstance(error.args[0][1], ProcessTerminated)

    def test_hung(self):
        """
        If the given command doesn't terminate with SIGTERM, it's SIGKILL'ed.
        """
        self.script.hang()
        self.fixture.protocol.timeout = 0.2
        self.fixture.setUp()
        self.fixture.cleanUp()
        self.assertIn(
            "Service process didn't terminate, trying to kill it",
            self.logger.output)


class ServiceProtocolIntegrationTest(TestCase):

    run_tests_with = AsynchronousDeferredRunTest.make_factory(timeout=5)

    def setUp(self):
        super(ServiceProtocolIntegrationTest, self).setUp()
        self.logger = self.useFixture(FakeLogger())
        self.protocol = ServiceProtocol()
        self.process = None
        self.script = self.useFixture(FakeExecutable())

    def tearDown(self):
        super(ServiceProtocolIntegrationTest, self).tearDown()
        if self.process and self.process.pid:
            os.kill(self.process.pid, signal.SIGKILL)
            return self.protocol.terminated

    @inlineCallbacks
    def test_ready(self):
        """
        The `ready` deferred fires when the service is ready.
        """
        self.script.sleep(1)
        self.process = reactor.spawnProcess(self.protocol, self.script.path)
        yield self.protocol.ready
        self.assertIn("Service process ready", self.logger.output)

    @inlineCallbacks
    def test_ready_with_expected_output(self):
        """
        If an expected output is provided, the 'ready' deferred fires only when
        that output gets emitted.
        """
        self.script.out("hello")
        self.script.sleep(1)
        self.protocol.expectedOutput = "hello"
        self.process = reactor.spawnProcess(self.protocol, self.script.path)
        yield self.protocol.ready
        self.assertIn("hello", self.logger.output)

    @inlineCallbacks
    def test_ready_with_expected_port(self):
        """
        If an expected output is provided, the 'ready' deferred fires only when
        that output gets emitted.
        """
        self.script.listen()
        self.script.sleep(1)
        self.protocol.expectedPort = self.script.port
        self.process = reactor.spawnProcess(self.protocol, self.script.path)
        yield self.protocol.ready
        sock = socket.socket()
        sock.connect(("localhost", self.script.port))
        self.addCleanup(sock.close)
        self.assertIn("Service opened port", self.logger.output)

    @inlineCallbacks
    def test_ready_with_expected_port_retry(self):
        """
        If the service takes a bit to listen to the expected port, the protocol
        will retry.
        """
        self.script.sleep(1)
        self.script.listen()
        self.script.sleep(1)
        self.protocol.expectedPort = self.script.port
        self.process = reactor.spawnProcess(self.protocol, self.script.path)
        yield self.protocol.ready
        sock = socket.socket()
        sock.connect(("localhost", self.script.port))
        self.addCleanup(sock.close)
        self.assertIn("Service port probe failed", self.logger.output)
        self.assertIn("Service opened port", self.logger.output)

    @inlineCallbacks
    def test_no_min_uptime(self):
        """If the service doesn't stay up for minUpTime, an error is raised."""
        # Spawn a non-existing process, which will make os.execvp fail,
        # triggering ServiceProtocol.processExited almost immediately.
        self.process = reactor.spawnProcess(self.protocol, b"/foo/bar")
        try:
            yield self.protocol.ready
        except ProcessTerminated as error:
            self.assertEqual(1, error.exitCode)
        else:
            self.fail(
                "The 'ready' deferred did not errback, while we were expecting"
                "an error, due to the process not staying up for at least 0.1"
                "seconds")

    @inlineCallbacks
    def test_no_expected_output_exit(self):
        """
        If the process exits while we're waiting for it to emit the expected
        output, the 'ready' deferred fires with an error.
        """
        self.script.sleep(0.2)
        self.protocol.expectedOutput = "hello"
        self.process = reactor.spawnProcess(self.protocol, self.script.path)
        try:
            yield self.protocol.ready
        except ProcessDone as error:
            self.assertEqual(0, error.exitCode)
        else:
            self.fail("The 'ready' deferred did not errback")

    @inlineCallbacks
    def test_no_expected_output_timeout(self):
        """
        If the process doesn't emit the expected output, the 'ready' deferred
        doesn't fire.
        """
        self.script.sleep(1)
        self.protocol.expectedOutput = "hello"
        self.protocol.ready.addTimeout(0.2, reactor)
        self.process = reactor.spawnProcess(self.protocol, self.script.path)
        try:
            yield self.protocol.ready
        except TimeoutError as error:
            self.assertEqual(0.2, error.args[0])
            self.assertNotIn("hello", self.logger.output)
        else:
            self.fail("The 'ready' deferred did not timeout while waiting"
                      "for output")

    @inlineCallbacks
    def test_no_expected_port_timeout(self):
        """
        If the process doesn't listen to the expected port, the 'ready'
        deferred doesn't fire.
        """
        self.script.sleep(1)
        self.protocol.expectedPort = 9999
        self.protocol.ready.addTimeout(0.2, reactor)
        self.process = reactor.spawnProcess(self.protocol, self.script.path)
        try:
            yield self.protocol.ready
        except TimeoutError as error:
            self.assertEqual(0.2, error.args[0])
        else:
            self.fail(
                "The 'ready' deferred did not timeout while waiting for"
                "the process to listen to the expected port")

    @inlineCallbacks
    def test_no_expected_port_exit(self):
        """
        If the process exits while we're waiting for it to open the expected
        port, the 'ready' deferred fires with an error.
        """
        self.script.sleep(0.2)
        self.protocol.expectedPort = 9999
        self.process = reactor.spawnProcess(self.protocol, self.script.path)
        try:
            yield self.protocol.ready
        except ProcessDone as error:
            self.assertEqual(0, error.exitCode)
        else:
            self.fail("The 'ready' deferred did not errback")
