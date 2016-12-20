from selenium.webdriver.common.desired_capabilities import DesiredCapabilities
from selenium.webdriver.remote import webdriver

from fixtures import TempDir

from txfixtures.service import Service

FORMAT = (
    "\[{levelname} +- +{Y}-{m}-{d}T{H}:{M}:{S}\.{msecs}Z\] {name} - {message}")


class PhantomJS(Service):
    """Start and stop a `phantomjs` process in the background. """

    def __init__(self, phantomjs="phantomjs", args=(), **kwargs):
        command = [phantomjs] + list(args)
        super(PhantomJS, self).__init__(command, **kwargs)

        #: Desired capabilities that will be passed to the webdriver.
        self.desiredCapabilities = DesiredCapabilities.PHANTOMJS

        #: A WebDriver instance pointing to the phantomjs process spawned
        #: by this fixture.
        self.webdriver = None

        self.expectOutput("running on port")
        self.setOutputFormat(FORMAT)

    def _setUp(self):
        self.expectPort(self.allocatePort())
        self._cookies = self.useFixture(TempDir()).join("phantomjs.cookies")
        super(PhantomJS, self)._setUp()
        url = "http://localhost:%d/wd/hub" % self.protocol.expectedPort
        self.webdriver = webdriver.WebDriver(
            command_executor=url,
            desired_capabilities=self.desiredCapabilities)

    @property
    def _args(self):
        return self.command[:] + [
            "--webdriver=%d" % self.protocol.expectedPort,
            "--cookies-file=%s" % self._cookies,
        ]
