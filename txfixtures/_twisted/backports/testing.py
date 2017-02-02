from twisted import version
from twisted.test.proto_helpers import MemoryReactorClock


class MemoryReactorClock16_5(MemoryReactorClock):

    def __init__(self):
        super(MemoryReactorClock16_5, self).__init__()
        self.running = False
        self.hasRun = False
        self.triggers = {}
        self.whenRunningHooks = []

    def run(self):
        assert self.running is False
        self.running = True
        self.hasRun = True

        for f, args, kwargs in self.whenRunningHooks:
            f(*args, **kwargs)

        self.stop()

    def crash(self):
        self.running = None
        self.hasCrashed = True

    def stop(self):
        self.running = False
        self.hasStopped = True

    def addSystemEventTrigger(self, phase, eventType, callable, *args, **kw):
        phaseTriggers = self.triggers.setdefault(phase, {})
        eventTypeTriggers = phaseTriggers.setdefault(eventType, [])
        eventTypeTriggers.append((callable, args, kw))

    def callWhenRunning(self, callable, *args, **kw):
        self.whenRunningHooks.append((callable, args, kw))


if (version.major, version.minor) < (16, 5):
    MemoryReactorClock = MemoryReactorClock16_5
