Run asynchronous code from test cases
=====================================

The :class:`~txfixtures.reactor.Reactor` fixture can be used to drive
asynchronous Twisted code from a regular synchronous Python
:class:`~testtools.TestCase`.

The approach differs from trial_ or `testtools twisted support`_:
instead of starting the reactor in the main thread and letting it spin
for a while waiting for the :class:`~twisted.internet.defer.Deferred`
returned by the test to fire, this fixture will keep the reactor
running in a background thread until cleanup.

When used with testresources_'s :class:`FixtureResource` and
:class:`OptimisingTestSuite`, this fixture makes it possible to have
full control and monitoring over long-running processes that should be
up for the whole test suite run, and maybe produce output useful for
the test itself.

The typical use case is integration testing.

.. doctest::


   >>> from testtools import TestCase

   >>> from twisted.internet import reactor
   >>> from twisted.internet.threads import blockingCallFromThread
   >>> from twisted.internet.utils import getProcessOutput

   >>> from txfixtures import Reactor

   >>> class TestUsingAsyncAPIs(TestCase):
   ...
   ...     def setUp(self):
   ...         super().setUp()
   ...         self.fixture = self.useFixture(Reactor(reactor=reactor))
   ...
   ...     def test_uptime(self):
   ...         out = blockingCallFromThread(reactor, getProcessOutput, b"uptime")
   ...         self.assertIn("load average", out.decode("utf-8"))
   ...
   >>> test = TestUsingAsyncAPIs(methodName="test_uptime")
   >>> test.run().wasSuccessful()
   True

.. _testresources: https://pypi.python.org/pypi/testresources
.. _`testtools twisted support`: https://testtools.readthedocs.io/en/latest/twisted-support.html
.. _trial: http://twistedmatrix.com/trac/wiki/TwistedTrial
