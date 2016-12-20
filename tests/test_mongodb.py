from testtools import TestCase

from fixtures import FakeLogger

from txfixtures.reactor import Reactor
from txfixtures.mongodb import MongoDB


class MongoDBIntegrationTest(TestCase):

    def setUp(self):
        super(MongoDBIntegrationTest, self).setUp()
        self.logger = self.useFixture(FakeLogger())
        self.useFixture(Reactor())
        self.mongodb = MongoDB(timeout=5)

    def test_client(self):
        """
        After setUp is run, the service is fully ready and the client
        connected.
        """
        self.useFixture(self.mongodb)
        info = self.mongodb.client.server_info()
        self.assertIsNotNone(info)
