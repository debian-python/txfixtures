import pymongo

from txfixtures.service import (
    TIMEOUT,
    Service
)

COMMAND = b"mongod"
FORMAT = (
    "{Y}-{m}-{d}T{H}:{M}:{S}\.{msecs}\+0000 {levelname} "
    "[A-Z]+ +\[{name}\] {message}")


class MongoDB(Service):
    """Start and stop a `mongodb` process in the background. """

    def __init__(self, reactor, command=COMMAND, args=None, env=None,
                 timeout=None):
        super(MongoDB, self).__init__(
            reactor, command=command, args=args, env=env, timeout=timeout)

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
        self.addDataDir()
        super(MongoDB, self)._setUp()
        uri = "mongodb://localhost:%d" % self.port
        self.client = pymongo.MongoClient(uri, **self.clientKwargs)
        self.addCleanup(self.client.close)

        # XXX Workaround pymongo leaving threads around.
        self.addCleanup(pymongo.periodic_executor._shutdown_executors)

    def _extraArgs(self):
        return [
            b"--port=%d" % self.port,
            b"--dbpath=%s" % self._data_dirs[0].encode("utf-8"),
            b"--nojournal",
        ]
