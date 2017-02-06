from unittest import skipIf

from testtools import TestCase

from fixtures import FakeLogger

from twisted import version as twistedVersion

from txfixtures.reactor import Reactor
from txfixtures.service import Service
from txfixtures.phantomjs import PhantomJS

hasTwist = (twistedVersion.major, twistedVersion.minor) >= (16, 5)


class PhantomJSIntegrationTest(TestCase):

    def setUp(self):
        super(PhantomJSIntegrationTest, self).setUp()
        self.logger = self.useFixture(FakeLogger())
        reactor = self.useFixture(Reactor())

        # Setup a local web server to test the WebDriver
        server = Service(reactor, "twist", args=["web"], timeout=5)
        server.expectOutput("Starting reactor...")
        server.expectPort(8080)
        self.useFixture(server)

        self.fixture = PhantomJS(reactor, timeout=10)

    @skipIf(not hasTwist, "twist executable not available")
    def test_webdriver(self):
        """After setUp is run, the service is fully ready."""
        self.useFixture(self.fixture)
        self.fixture.webdriver.get("http://localhost:8080")
        self.assertEqual("Twisted Web Demo", self.fixture.webdriver.title)
