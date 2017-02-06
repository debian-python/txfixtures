Setup a phantomjs Selenium driver
=================================

The :class:`~txfixtures.phantomjs.PhantomJS` fixture starts a
phantomjs_ service in the background and exposes it via its
`webdriver` attribute, which can then be used by test cases for
Selenium_-based assertions:

.. doctest::

   >>> from fixtures import FakeLogger
   >>> from testtools import TestCase
   >>> from txfixtures import Reactor, Service, PhantomJS

   >>> TWISTD = "twistd"
   >>> TWISTD_ARGS = "-n web".split(" ")

   >>> class HTTPServerTest(TestCase):
   ...
   ...     def setUp(self):
   ...         super().setUp()
   ...         self.logger = self.useFixture(FakeLogger())
   ...         reactor = self.useFixture(Reactor())
   ...
   ...         # Create a sample web server
   ...         self.service = Service(reactor, TWISTD, args=TWISTD_ARGS)
   ...         self.service.expectPort(8080)
   ...         self.useFixture(self.service)
   ...
   ...         self.phantomjs = self.useFixture(PhantomJS(reactor))
   ...
   ...     def test_home_page(self):
   ...         self.phantomjs.webdriver.get("http://localhost:8080")
   ...         self.assertEqual("Twisted Web Demo", self.phantomjs.webdriver.title)

   >>> test = HTTPServerTest(methodName="test_home_page")
   >>> test.run().wasSuccessful()
   True

.. _phantomjs: http://phantomjs.org
.. _Selenium: http://selenium-python.readthedocs.io/
