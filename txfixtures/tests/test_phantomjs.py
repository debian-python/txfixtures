import os

from testtools import TestCase
from testtools.matchers import (
    StartsWith,
    DirExists,
)

from selenium.webdriver.remote import webdriver

from fixtures import FakeLogger

from txfixtures._twisted.testing import ThreadedMemoryReactorClock

from txfixtures.phantomjs import PhantomJS

OUT = (
    b"[INFO  - 2016-11-17T09:01:38.591Z] GhostDriver - ",
    b"Main - running on port 666",
    b""
)


class PhantomJSTest(TestCase):

    def setUp(self):
        super(PhantomJSTest, self).setUp()
        self.logger = self.useFixture(FakeLogger())
        self.reactor = ThreadedMemoryReactorClock()
        self.fixture = PhantomJS(reactor=self.reactor)

    def test_setup(self):
        """
        The fixture passes port and cookies paths as extra argument, and
        configure the output format to match phantomjs' one.
        """
        self.reactor.process.data = b"\n".join(OUT)

        class FakeWebDriver(object):

            def __init__(self, **kwargs):
                pass

        self.patch(self.fixture, "allocatePort", lambda: 666)
        self.patch(webdriver, "WebDriver", FakeWebDriver)

        self.fixture.setUp()
        executable, arg1, arg2 = self.reactor.process.args
        self.assertEqual("phantomjs", executable)
        self.assertEqual("--webdriver=666", arg1)
        self.assertThat(arg2, StartsWith("--cookies-file="))
        self.assertThat(os.path.dirname(arg2.split("=")[1]), DirExists())
        self.assertIn("running on port 666", self.logger.output)
