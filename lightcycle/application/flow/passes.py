import sys

from lightcycle.application.flow.park_step import ParkInput, ParkStepUseCase
from lightcycle.domain.runs import RunState, parse_slices
from lightcycle.ports.git import GitReadError


class PassBook:
    def __init__(self, store, flow):
        self._store = store
        self._flow = flow

    def current(self, item):
        return self._store.current_pass(item) or self._store_open(item)

    def _store_open(self, item):
        return self._store.get_pass(self._store.open_pass(item))

    def enrol(self, item, step_id, stage, name=None, completing=None):
        pass_record = self.current(item)
        self._store.set_step_pass(step_id, pass_record.id)
        phase = self._flow.phase_for_stage(stage, name)
        sliced_phase, artifact = self._flow.slicing(name)
        if sliced_phase is not None and phase == sliced_phase and completing is not None:
            if self._flow.phase_for_stage(completing.stage, name) == sliced_phase:
                return self._open_in_slice(
                    item, pass_record, phase, completing.slice, step_id)
            return self._enter_sliced_phase(
                item, pass_record, phase, artifact, step_id, completing)
        return self._open_in_slice(item, pass_record, phase, 0, step_id)

    def _open_in_slice(self, item, pass_record, phase, slice, step_id):
        if slice:
            self._store.set_step_slice(step_id, slice)
        if self._store.current_run(item, phase, slice) is None:
            self._store.open_run(item, pass_record.id, phase, slice)
        return pass_record

    def _enter_sliced_phase(self, item, pass_record, phase, artifact, step_id, completing):
        text = next(
            (a.value for a in reversed(self._store.item_artifacts(item)) if a.type == artifact),
            None,
        )
        try:
            slices = parse_slices(text)
        except ValueError as e:
            self._open_in_slice(item, pass_record, phase, 0, step_id)
            ParkStepUseCase(self._store).execute(ParkInput(
                step=step_id,
                observation="the %s artifact does not parse: %s" % (artifact, e),
                decision="fix the %s artifact with lc attach, then reroute this step" % artifact,
            ))
            return pass_record
        if len(slices) < 2:
            return self._open_in_slice(item, pass_record, phase, 0, step_id)
        entry = self._store.get_node(step_id)
        for sl in slices:
            self._store.open_run(
                item, pass_record.id, phase, sl.number, sl.name, sl.base)
            if sl.number == 1:
                self._store.set_step_slice(step_id, 1)
                continue
            sibling = self._store.create_step(
                stage=entry.stage, role=entry.role, item=item, deps=[item],
                previous=completing.id, slice=sl.number)
            self._store.set_step_pass(sibling, pass_record.id)
        return pass_record

    def defers_to_last_slice(self, t, outcome, name=None):
        if t.slice <= 0 or not t.item:
            return False
        if self._flow.merge_outcome(t.stage, name) != outcome:
            return False
        pass_record = self._store.current_pass(t.item)
        if pass_record is None:
            return False
        return any(
            r.slice > 0 and r.slice != t.slice and r.phase == self._flow.phase_for_stage(t.stage, name)
            for r in self._store.open_runs_of(t.item, pass_record.id)
        )

    def close_slice_run(self, t, name=None):
        phase = self._flow.phase_for_stage(t.stage, name)
        run = self._store.current_run(t.item, phase, t.slice)
        if run is not None:
            self._store.close_run(run.id, RunState.MERGED)
        return run

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
