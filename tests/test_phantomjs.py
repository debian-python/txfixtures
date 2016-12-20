from testtools import TestCase

from fixtures import FakeLogger

from txfixtures.reactor import Reactor
from txfixtures.service import Service
from txfixtures.phantomjs import PhantomJS


class PhantomJSIntegrationTest(TestCase):

    def setUp(self):
        super(PhantomJSIntegrationTest, self).setUp()
        self.logger = self.useFixture(FakeLogger())
        self.useFixture(Reactor())

        # Setup a local web server to test the WebDriver
        server = Service(["twist", "web"], timeout=5)
        server.expectOutput("Starting reactor...")
        server.expectPort(8080)
        self.useFixture(server)

        self.fixture = PhantomJS(timeout=5)

    def test_webdriver(self):
        """After setUp is run, the service is fully ready."""
        self.useFixture(self.fixture)
        self.fixture.webdriver.get("http://localhost:8080")
        self.assertEqual("Twisted Web Demo", self.fixture.webdriver.title)
