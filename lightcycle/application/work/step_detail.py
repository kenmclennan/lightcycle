from lightcycle.application.work.step_run import StepRunInput, StepRunUseCase
from lightcycle.domain.work.detail import (
    CI_CHECKS_ROW,
    CI_JUDGED_SHA,
    IN_PREFIX,
    SPEC_PHASE,
    SPEC_PR_ROW,
    SPEC_ROW,
    ci_checks_url,
    default_detail,
    detail_presents,
    leading_run_names,
    resolve_detail,
    with_leading,
    with_park,
)


class StepDetail:
    def __init__(self, store, flow):
        self._store = store
        self._flow = flow

    def resolve(self, step, inputs, output_entries, run=None, worktree=None):
        if run is None:
            run = StepRunUseCase(self._store, self._flow).execute(StepRunInput(step=step.id))
        step_def = self._flow.flow_for(step).step_def(step.stage)
        parked = bool(step.park.reason or step.park.needs)
        pr = run.pr or self._phase_pr(step)
        has_run = bool(pr or run.branch)
        names = step_def.detail or default_detail(has_run, step_def.presents)
        spec_run = self._spec_run(run)
        spec = next(
            (a.value for a in self._store.item_artifacts(step.item) if a.kind == "filepath"),
            None,
        )
        ci_sha = self._latest_artifact(step.id, CI_JUDGED_SHA) or (
            self._latest_artifact(step.previous_step, CI_JUDGED_SHA)
            if step.previous_step else None)
        if has_run:
            leading = leading_run_names(spec_run is not None, bool(spec), bool(ci_sha))
            names = with_leading(leading, names)
        names = with_park(names, parked)
        session = self._latest_artifact(step.id, "session-id")
        fields = {
            "pr": pr,
            SPEC_PR_ROW: spec_run.pr if spec_run is not None else None,
            "branch": run.branch,
            "worktree": worktree,
            SPEC_ROW: spec,
            CI_CHECKS_ROW: ci_checks_url(pr, ci_sha),
            "outcome": step.outcome,
            "report": step.report,
            "claimed_by": step.claimed_by,
            "model": step.model,
            "session": session,
            "needs": step.park.needs,
            "reason": step.park.reason,
        }
        entries = resolve_detail(
            names, fields, self._input_values(names, inputs),
            {e["name"]: e["value"] for e in output_entries},
        )
        return entries, detail_presents(step_def.presents, entries)

    def _phase_pr(self, step):
        phase = self._flow.phase_for(step)
        if phase is None:
            return None
        runs = [r for r in self._store.runs_of(step.item) if r.phase == phase and r.pr]
        if not runs:
            return None
        return max(runs, key=lambda r: r.opened_at or "").pr

    def _spec_run(self, run):
        if not run.pass_id or run.phase == SPEC_PHASE:
            return None
        return next(
            (r for r in self._store.runs_of(run.item, run.pass_id) if r.phase == SPEC_PHASE),
            None,
        )

    def _latest_artifact(self, node_id, atype):
        found = None
        for artifact in self._store.item_artifacts(node_id):
            if artifact.type == atype:
                found = artifact.value
        return found

    @staticmethod
    def _input_values(names, inputs):
        wanted = [n[len(IN_PREFIX):] for n in names if n.startswith(IN_PREFIX)]
        if not wanted or not inputs:
            return {}
        context = inputs.get("context") or {}
        previous = inputs.get("previous") or {}
        found = {}
        for name in wanted:
            value = None
            for entry in previous.get("outputs") or []:
                if entry["name"] == name:
                    value = entry["value"]
            if value is None:
                for entry in inputs.get("item") or []:
                    if entry["name"] == name:
                        value = entry["value"]
            if value is None and name == "report":
                value = previous.get("report")
            if value is None:
                value = context.get(name)
            found[name] = value
        return found
