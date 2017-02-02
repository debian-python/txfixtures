from twisted.python import failure
from twisted.internet.defer import CancelledError, TimeoutError


def addTimeout(deferred, timeout, clock, onTimeoutCancel=None):
    """Backport of Deferred.addTimeout, which is only available on >=16.5."""

    # Use the stock addTimeout if available
    if hasattr(deferred, "addTimeout"):
        return deferred.addTimeout(
            timeout, clock, onTimeoutCancel=onTimeoutCancel)

    timedOut = [False]

    def timeItOut():
        timedOut[0] = True
        deferred.cancel()

    delayedCall = clock.callLater(timeout, timeItOut)

    def convertCancelled(value):
        # if C{deferred} was timed out, call the translation function,
        # if provdied, otherwise just use L{cancelledToTimedOutError}
        if timedOut[0]:
            toCall = onTimeoutCancel or _cancelledToTimedOutError
            return toCall(value, timeout)
        return value

    deferred.addBoth(convertCancelled)

    def cancelTimeout(result):
        # stop the pending call to cancel the deferred if it's been fired
        if delayedCall.active():
            delayedCall.cancel()
        return result

    deferred.addBoth(cancelTimeout)
    return deferred


def _cancelledToTimedOutError(value, timeout):
    if isinstance(value, failure.Failure):
        value.trap(CancelledError)
        raise TimeoutError(timeout, "Deferred")
    return value
