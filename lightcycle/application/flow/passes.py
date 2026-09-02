from lightcycle.domain.runs import RunState


class PassBook:
    def __init__(self, store, flow):
        self._store = store
        self._flow = flow

    def current(self, item):
        return self._store.current_pass(item) or self._store_open(item)

    def _store_open(self, item):
        return self._store.get_pass(self._store.open_pass(item))

    def enrol(self, item, step_id, stage, name=None):
        pass_record = self.current(item)
        self._store.set_step_pass(step_id, pass_record.id)
        phase = self._flow.phase_for_stage(stage, name)
        run = self._store.current_run(item, phase)
        if run is None:
            self._store.open_run(item, pass_record.id, phase)
        return pass_record

    def ends_pass(self, stage, outcome, name=None):
        return self._flow.ends_pass(stage, outcome, name)

    def close(self, item, worktrees=None):
        pass_record = self._store.current_pass(item)
        if pass_record is None:
            return []
        closed = []
        for run in self._store.open_runs_of(item, pass_record.id):
            self.close_run(run, RunState.MERGED, worktrees)
            closed.append(run.id)
        self._store.close_pass(pass_record.id)
        return closed

    def close_run(self, run, state, worktrees=None):
        self._store.close_run(run.id, state)
        if worktrees is not None:
            worktrees.release_run(run)
