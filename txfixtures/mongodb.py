import pymongo

from fixtures import TempDir

from txfixtures.service import Service

FORMAT = (
    "{Y}-{m}-{d}T{H}:{M}:{S}\.{msecs}\+0000 {levelname} "
    "[A-Z]+ +\[{name}\] {message}")


class MongoDB(Service):
    """Start and stop a `mongodb` process in the background. """

    def __init__(self, mongod="mongod", args=(), **kwargs):
        command = [mongod] + list(args)
        super(MongoDB, self).__init__(command, **kwargs)

        self.expectOutput("waiting for connections on port")
        self.setOutputFormat(FORMAT)
        self.setClientKwargs()

    def setClientKwargs(self, **kwargs):
        """Additional keyword arguments to pass to the client."""
        self.clientKwargs = kwargs

    @property
    def port(self):
        return self.protocol.expectedPort

    def _setUp(self):
        self.expectPort(self.allocatePort())
        self._dbPath = self.useFixture(TempDir())
        super(MongoDB, self)._setUp()
        uri = "mongodb://localhost:%d" % self.port
        self.client = pymongo.MongoClient(uri, **self.clientKwargs)
        self.addCleanup(self.client.close)

        # XXX Workaround pymongo leaving threads around.
        self.addCleanup(pymongo.periodic_executor._shutdown_executors)

    @property
    def _args(self):
        return self.command[:] + [
            "--port=%d" % self.port,
            "--dbpath=%s" % self._dbPath.path,
        ]
