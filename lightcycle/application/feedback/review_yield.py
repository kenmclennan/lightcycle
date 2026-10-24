import json

from lightcycle.application.flow.engine_steps import (
    AUDIT_STEP,
    DAILY_SUMMARY_STEP,
    FINDINGS_STEP,
    HELD_COMMENT_STEP,
    LIFECYCLE_FAILURE_STEP,
    MATERIAL_AUDIT_STEP,
)
from lightcycle.domain.feedback.review_yield import (
    CAUSED_BY,
    FOUND_BY,
    REVIEW_FINDINGS,
    latest_passing_verdict,
)
from lightcycle.domain.money import Cost
from lightcycle.domain.work import State
from lightcycle.domain.workflows.identity import parse_pin
from lightcycle.ports.store import NodeNotFoundError

_ENGINE_STAGES = frozenset({
    AUDIT_STEP, MATERIAL_AUDIT_STEP, FINDINGS_STEP, DAILY_SUMMARY_STEP, HELD_COMMENT_STEP,
    LIFECYCLE_FAILURE_STEP,
})

POST_MERGE = "post-merge"
REWORK = "rework"


class _Stage:
    def __init__(self, workflow, stage, pass_outcome):
        self.workflow = workflow
        self.stage = stage
        self.pass_outcome = pass_outcome
        self.verdict_rows = []
        self.escape_rows = []

    def as_dict(self):
        passes = sum(1 for r in self.verdict_rows if r["outcome"] == self.pass_outcome)
        reported = [r for r in self.verdict_rows if r["findings"] is not None]
        by_source = {}
        for row in self.escape_rows:
            key = row["source"] if row["kind"] == REWORK else POST_MERGE
            by_source[key] = by_source.get(key, 0) + 1
        cost = Cost()
        for row in self.verdict_rows:
            cost = cost + Cost.from_usd(row["cost_usd"])
        return {
            "workflow": self.workflow,
            "stage": self.stage,
            "pass_outcome": self.pass_outcome,
            "verdicts": len(self.verdict_rows),
            "passes": passes,
            "rejections": len(self.verdict_rows) - passes,
            "cost_usd": cost.to_usd(),
            "findings": {
                "verdicts_with_findings": sum(1 for r in reported if r["findings"]),
                "verdicts_reporting_none": sum(1 for r in reported if not r["findings"]),
                "count": sum(len(r["findings"]) for r in reported),
            },
            "escapes": {"count": len(self.escape_rows), "by_source": by_source},
            "verdict_rows": self.verdict_rows,
            "escape_rows": self.escape_rows,
        }


class ReviewYieldUseCase:
    def __init__(self, store, flow):
        self._store = store
        self._flow = flow

    def execute(self, since):
        floor = since or ""
        stages = {}
        undeclared = 0
        for step in self._store.nodes_closed_since(floor):
            if step.type != "step" or step.state != State.DONE or step.stage in _ENGINE_STAGES:
                continue
            definition = self._definition(step)
            if definition is None:
                undeclared += 1
            elif definition.review is not None:
                self._verdict_row(stages, step, definition)
        unattributed = []
        for escape in self._store.escapes_since(floor):
            group = self._group_of(stages, escape.verdict_step)
            row = {
                "kind": REWORK, "item": escape.item, "at": escape.at,
                "verdict_step": escape.verdict_step, "source": escape.source,
                "authors": escape.authors, "note": escape.note, "via": escape.via,
            }
            (unattributed if group is None else group.escape_rows).append(row)
        for item_id, artifact in self._store.artifacts_of_type(CAUSED_BY):
            self._post_merge(stages, unattributed, floor, item_id, artifact.value)
        ordered = sorted(stages.values(), key=lambda g: (g.workflow or "", g.stage))
        return {
            "since": since,
            "stages": [g.as_dict() for g in ordered],
            "unattributed_escapes": unattributed,
            "undeclared_steps": undeclared,
        }

    def _definition(self, step):
        flow = self._flow.flow_for(step)
        if not flow.declared(step.stage):
            return None
        return flow.step_def(step.stage)

    def _workflow_name(self, item):
        pin = self._store.item_workflow(item)
        parsed = parse_pin(pin) if pin else None
        return "%s/%s" % (parsed[0], parsed[1]) if parsed else pin

    def _group(self, stages, step, definition):
        key = (self._workflow_name(step.item), step.stage)
        if key not in stages:
            stages[key] = _Stage(key[0], key[1], definition.review)
        return stages[key]

    def _findings_of(self, step):
        for artifact in self._store.item_artifacts(step.id):
            if artifact.type == REVIEW_FINDINGS:
                return json.loads(artifact.value)
        return None

    def _verdict_row(self, stages, step, definition):
        group = self._group(stages, step, definition)
        group.verdict_rows.append({
            "step": step.id, "item": step.item, "pass": step.pass_id,
            "phase": definition.phase, "outcome": step.outcome, "closed_at": step.closed_at,
            "cost_usd": step.usage_cost_usd.to_usd(), "findings": self._findings_of(step),
        })

    def _group_of(self, stages, verdict_step):
        try:
            verdict = self._store.get_node(verdict_step)
        except (KeyError, NodeNotFoundError):
            return None
        definition = self._definition(verdict)
        if definition is None or definition.review is None:
            return None
        return self._group(stages, verdict, definition)

    def _passing_verdict(self, item):
        passed = []
        for child in self._store.children(item):
            if getattr(child, "type", None) != "step" or child.state != State.DONE:
                continue
            definition = self._definition(child)
            if definition is not None and child.outcome == definition.review:
                passed.append(child)
        return latest_passing_verdict(passed)

    def _post_merge(self, stages, unattributed, floor, fix_item, source_item):
        try:
            fix = self._store.get_item(fix_item)
        except (KeyError, NodeNotFoundError):
            return
        if (fix.created_at or "")[:10] < floor:
            return
        found_by = next(
            (a.value for a in self._store.item_artifacts(fix_item) if a.type == FOUND_BY), None)
        verdict = self._passing_verdict(source_item)
        row = {
            "kind": POST_MERGE, "item": fix_item, "at": fix.created_at,
            "verdict_step": verdict.id if verdict else None, "linked_item": source_item,
            "found_by": found_by, "authors": None, "note": None, "via": None,
        }
        if verdict is None:
            unattributed.append(row)
            return
        self._group(stages, verdict, self._definition(verdict)).escape_rows.append(row)
