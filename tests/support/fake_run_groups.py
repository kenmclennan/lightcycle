from lightcycle.ports.run_groups import RunGroupsPort, StoppedRuns


class FakeRunGroups(RunGroupsPort):
    def __init__(self, stopped=None):
        self.stopped = stopped if stopped is not None else StoppedRuns()
        self.stop_graces = []
        self.registered = {}

    def register(self, label, proc):
        self.registered[proc.pid] = label

    def release(self, proc):
        self.registered.pop(proc.pid, None)

    def stop(self, grace_seconds):
        self.stop_graces.append(grace_seconds)
        return self.stopped
