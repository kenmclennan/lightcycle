import sys

from lightcycle.domain.runs import RunState
from lightcycle.ports.git import GitReadError


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

    def release_refusals(self, item, worktrees):
        if worktrees is None:
            return []
        pass_record = self._store.current_pass(item)
        if pass_record is None:
            return []
        return worktrees.pass_release_refusals(item, self._store.open_runs_of(item, pass_record.id))

    def close_in_transaction(self, item):
        pass_record = self._store.current_pass(item)
        if pass_record is None:
            return []
        closed = list(self._store.open_runs_of(item, pass_record.id))
        for run in closed:
            self._store.close_run(run.id, RunState.MERGED)
        self._store.close_pass(pass_record.id)
        return closed

    def release_runs(self, runs, worktrees=None):
        if worktrees is None:
            return True
        released = True
        for run in runs:
            released = self._release_one(run, worktrees) and released
        return released

    def _release_one(self, run, worktrees):
        try:
            worktrees.release_run(run)
        except GitReadError as e:
            print(
                "warning: release of %s failed, release-pending marker kept: %s" % (run.id, e),
                file=sys.stderr,
            )
            return False
        return True

    def close_run(self, run, state, worktrees=None):
        self._store.close_run(run.id, state)
        if worktrees is not None:
            self._release_one(run, worktrees)
