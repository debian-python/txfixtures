import pymongo

from testtools import TestCase
from testtools.matchers import (
    StartsWith,
    DirExists,
)

from fixtures import FakeLogger

from txfixtures._twisted.testing import ThreadedMemoryReactorClock
from txfixtures.reactor import Reactor
from txfixtures.mongodb import MongoDB

OUT = (
    b"2016-11-30T10:35:25.476+0000 I CONTROL  [init] MongoDB starting",
    b"2016-11-30T10:35:25.948+0000 I NETWORK  [init] waiting for connections on port 666",
    b"",
)


class MongoDBTest(TestCase):

    def setUp(self):
        super(MongoDBTest, self).setUp()
        self.logger = self.useFixture(FakeLogger())
        self.reactor = ThreadedMemoryReactorClock()
        self.fixture = MongoDB(Reactor(self.reactor))

    def test_setup(self):
        """
        The fixture passes port and dbpath as extra arguments, and
        configure the output format to match mongodb's one.
        """
        self.reactor.process.data = b"\n".join(OUT)
        client = []

        class FakeMongoClient(object):

            def __init__(self, endpoint):
                client.append(endpoint)

            def close(self):
                client.append("close")

        self.patch(self.fixture, "allocatePort", lambda: 666)
        self.patch(pymongo, "MongoClient", FakeMongoClient)

        self.fixture.setUp()
        executable, arg1, arg2, arg3 = self.reactor.process.args
        self.assertEqual(b"mongod", executable)
        self.assertEqual(b"--port=666", arg1)
        self.assertEqual(["mongodb://localhost:666"], client)
        self.assertThat(arg2, StartsWith(b"--dbpath="))
        self.assertThat(arg2.split(b"=")[1], DirExists())
        self.assertEqual(b"--nojournal", arg3)
        self.assertIn(
            "waiting for connections on port 666",
            self.logger.output.split("\n"))

        self.fixture.cleanUp()
        self.assertEqual(["mongodb://localhost:666", "close"], client)
