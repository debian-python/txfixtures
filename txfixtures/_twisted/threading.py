"""Extensions to stock Twisted code."""

from six.moves.queue import (
    Queue,
    Empty,
)

from twisted.internet.defer import maybeDeferred
from twisted.python.failure import Failure


class CallFromThreadTimeout(Exception):
    """Raised when interruptableCallFromThread times out."""


def interruptableCallFromThread(reactor, timeout, f, *a, **kw):
    """An interruptable version of Twisted's blockingCallFromThread.

    This function has all arguments and semantics of the original one, plus
    a new 'timeout' argument that will make the call fail after the given
    amount of seconds.
    """
    queue = Queue()

    def _callFromThread(queue, f):
        result = maybeDeferred(f, *a, **kw)
        result.addBoth(queue.put)
    reactor.callFromThread(_callFromThread, queue, f)
    try:
        result = queue.get(timeout=timeout)
    except Empty:
        raise CallFromThreadTimeout()
    if isinstance(result, Failure):
        result.raiseException()
    return result
