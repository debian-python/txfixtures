Spawn, control and monitor test services
========================================

The :class:`~txfixtures.service.Service` fixture can be used to spawn
a background service process (for instance a web application), and
leave it running for the duration of the test suite (see
:ref:`testresources-integration`).

It supports real-time streaming of the service standard output to Python's
:py:mod:`logging` system.

Spawn a simple service fixture listening to a port
--------------------------------------------------

Let's create a test that spawns a dummy HTTP server that listens to
port 8080:

.. doctest::

   >>> import socket

   >>> from testtools import TestCase
   >>> from txfixtures import Reactor, Service

   >>> PYTHON = "python3"
   >>> PYTHON_HTTP_ARGS = "-m http.server 8080".split(" ")

   >>> class HTTPServerTest(TestCase):
   ...
   ...     def setUp(self):
   ...         super().setUp()
   ...         reactor = self.useFixture(Reactor())
   ...
   ...         # Create a service fixture that will spawn the HTTP server
   ...         # and wait for it to listen to port 8080.
   ...         self.service = Service(reactor, PYTHON, args=PYTHON_HTTP_ARGS)
   ...         self.service.expectPort(8080)
   ...
   ...         self.useFixture(self.service)
   ...
   ...     def test_connect(self):
   ...         connection = socket.socket()
   ...         connection.connect(("127.0.0.1", 8080))
   ...         self.assertEqual(connection.getsockname()[0], "127.0.0.1")

   >>> test = HTTPServerTest(methodName="test_connect")
   >>> test.run().wasSuccessful()
   True

Forward standard output to the Python logging system
-----------------------------------------------------

Let's spawn a simple HTTP server and have its standard output forwarded to
the Python logging system:

.. doctest::

   >>> import requests

   >>> from fixtures import FakeLogger

   >>> TWISTD = "twistd"
   >>> TWISTD_ARGS = "-n web".split(" ")

   # This format string will be used to build a regular expression to parse
   # each output line of the service, and map it to a Python LogRecord. A
   # sample output line from the twistd web command looks like:
   #
   #   2016-11-17T22:18:36+0000 [-] Site starting on 8080
   #
   >>> TWISTD_FORMAT = "{Y}-{m}-{d}T{H}:{M}:{S}\+0000 \[{name}\] {message}"

   # This output string will be used as a "marker" indicating that the service
   # has initialized, and should shortly start listening to the expected port (if
   # one was given). The fixture.setUp() method will intercept this marker and
   # then wait for the service to actually open the port.
   >>> TWISTD_OUTPUT = "Site starting on 8080"

   >>> class TwistedWebTest(TestCase):
   ...
   ...     def setUp(self):
   ...         super().setUp()
   ...         self.logger = self.useFixture(FakeLogger())
   ...         reactor = self.useFixture(Reactor())
   ...         self.service = Service(reactor, TWISTD, args=TWISTD_ARGS)
   ...         self.service.setOutputFormat(TWISTD_FORMAT)
   ...         self.service.expectOutput(TWISTD_OUTPUT)
   ...         self.service.expectPort(8080)
   ...         self.useFixture(self.service)
   ...
   ...     def test_request(self):
   ...         response = requests.get("http://localhost:8080")
   ...         self.assertEqual(200, response.status_code)
   ...         self.assertIn('"GET / HTTP/1.1" 200', self.logger.output)
   ...
   >>> test = TwistedWebTest(methodName="test_request")
   >>> test.run().wasSuccessful()
   True
