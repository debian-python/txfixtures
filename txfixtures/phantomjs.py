import os

from selenium.webdriver.common.desired_capabilities import DesiredCapabilities
from selenium.webdriver.remote import webdriver

from txfixtures.service import (
    TIMEOUT,
    Service,
)

COMMAND = b"phantomjs"
FORMAT = (
    "\[{levelname} +- +{Y}-{m}-{d}T{H}:{M}:{S}\.{msecs}Z\] {name} - {message}")


class PhantomJS(Service):
    """Start and stop a `phantomjs` process in the background. """

    def __init__(self, reactor, command=COMMAND, args=None, env=None,
                 timeout=None):
        super(PhantomJS, self).__init__(
            reactor, command=command, args=args, env=env, timeout=timeout)

        #: Desired capabilities that will be passed to the webdriver.
        self.desiredCapabilities = DesiredCapabilities.PHANTOMJS

        #: A WebDriver instance pointing to the phantomjs process spawned
        #: by this fixture.
        self.webdriver = None

        self.expectOutput("running on port")
        self.setOutputFormat(FORMAT)

    def _setUp(self):
        self.expectPort(self.allocatePort())
        self.addDataDir()
        super(PhantomJS, self)._setUp()
        url = "http://localhost:%d/wd/hub" % self.protocol.expectedPort
        self.webdriver = webdriver.WebDriver(
            command_executor=url,
            desired_capabilities=self.desiredCapabilities)

    def _extraArgs(self):
        cookies_file = os.path.join(self._data_dirs[0], "phantomjs.cookies")
        return [
            "--webdriver=%d" % self.protocol.expectedPort,
            "--cookies-file=%s" % cookies_file,
        ]
