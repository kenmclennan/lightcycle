from dataclasses import dataclass
from typing import Optional

from lightcycle.application.errors import UseCaseError
from lightcycle.application.flow.engine_steps import (
    AUDIT_STEP, DAILY_SUMMARY_STEP, FINDINGS_STEP, HELD_COMMENT_ORIGIN_LABEL, HELD_COMMENT_STEP,
    LIFECYCLE_FAILURE_STEP, LIFECYCLE_ORIGIN_LABEL, MATERIAL_AUDIT_STEP, RETRO_ORIGIN_LABEL,
    SUMMARY_ORIGIN_LABEL, engine_outcomes_for_node,
)
from lightcycle.domain.feedback import RETROED_LABEL
from lightcycle.application.flow.next_step import NextStepResolver
from lightcycle.application.flow.passes import PassBook
from lightcycle.application.flow.schedule_completion import ScheduleCompletion
from lightcycle.application.flow.park_step import ParkInput, ParkStepUseCase
from lightcycle.application.work.close_item import (
    RELEASE_PENDING_LABEL, CloseItemInput, CloseItemUseCase,
)
from lightcycle.application.work.closed_count import closed_count
from lightcycle.application.work.has_feedback import has_feedback
from lightcycle.application.work.item_outputs import ItemOutputs
from lightcycle.application.work.step_inputs import StepInputs
from lightcycle.application.work.pending_reflections import pass_reflection_count
from lightcycle.domain.contracts import StepContract
from lightcycle.domain.work import NodeSpec
from lightcycle.domain.work.state import State

_AUTO_CLOSE_REASON = "auto-closed: all children done"


@dataclass(frozen=True)
class CompleteInput:
    step: str
    outcome: str
    note: Optional[str] = None


@dataclass(frozen=True)
class ClosePlan:
    close: CloseItemInput
    findings: tuple


@dataclass(frozen=True)
class CompleteResponse:
    next_step: Optional[str]
    teardown_refusal: Optional[str] = None


class CompleteStepUseCase:
    def __init__(self, store, flow, worktrees=None, config=None):
        self._store = store
        self._flow = flow
        self._worktrees = worktrees
        self._config = config
        self._resolver = NextStepResolver(store, flow)
        self._passes = PassBook(store, flow)
        self._inputs = StepInputs(store, flow)
        self._outputs = ItemOutputs(store, flow)
        self._closer = CloseItemUseCase(store, worktrees)

    def _expected_assignee(self):
        return self._config.spawn_id() if self._config else None

    def execute(self, input: CompleteInput) -> CompleteResponse:
        t = self._store.get_node(input.step)
        repair = t.state == State.DONE
        if repair and t.outcome != input.outcome:
            return CompleteResponse(next_step=None)
        valid = engine_outcomes_for_node(self._store, t)
        if valid is not None and input.outcome not in valid:
            raise UseCaseError(
                "no transition for step=%s outcome=%s; not closing. Valid outcomes: %s."
                % (t.stage, input.outcome, ", ".join(valid))
            )
        if self._is_retro_origin(t):
            if t.stage == AUDIT_STEP:
                return self._complete_engine_audit(t, input, True, repair)
            if t.stage == MATERIAL_AUDIT_STEP:
                return self._complete_engine_audit(t, input, False, repair)
            if t.stage == FINDINGS_STEP:
                return self._complete(t, input, repair=repair)
        if self._is_summary_origin(t) and t.stage == DAILY_SUMMARY_STEP:
            return self._complete(t, input, writes=self._day_summary_writes(t, input),
                                  repair=repair)
        if self._is_held_comment_origin(t) and t.stage == HELD_COMMENT_STEP:
            return self._complete_held_comment(t, input, repair)
        if self._is_lifecycle_origin(t) and t.stage == LIFECYCLE_FAILURE_STEP:
            return self._complete(t, input, repair=repair)
        return self._complete_workflow(t, input, repair)

    def _is_lifecycle_origin(self, t):
        return LIFECYCLE_ORIGIN_LABEL in self._store.labels_of(t.item)

    def _is_held_comment_origin(self, t):
        return HELD_COMMENT_ORIGIN_LABEL in self._store.labels_of(t.item)

    def _is_retro_origin(self, t):
        return RETRO_ORIGIN_LABEL in self._store.labels_of(t.item)

    def _is_summary_origin(self, t):
        return SUMMARY_ORIGIN_LABEL in self._store.labels_of(t.item)

    def _complete_held_comment(self, t, input: CompleteInput, repair) -> CompleteResponse:
        decided = "approved" if input.outcome == "approve" else "rejected"

        def writes(_new):
            if not repair:
                self._store.decide_hold(t.id, decided)

        return self._complete(t, input, writes=writes, repair=repair)

    def _complete(
        self, t, input: CompleteInput, spec=None, writes=None, ends_pass=False, enrol=None,
        repair=False,
    ) -> CompleteResponse:
        plan = self._close_plan(t, spec is not None)
        runs = []
        refusal = None
        closed = False
        new = None
        with self._store.transaction():
            if not repair:
                won, new = self._store.complete_step_atomic(
                    input.step, input.outcome, self._expected_assignee(), spec)
                if not won:
                    return CompleteResponse(next_step=None)
                if ends_pass:
                    runs = self._passes.close_in_transaction(t.item)
                    if runs and self._worktrees is not None:
                        self._store.label_add(t.item, RELEASE_PENDING_LABEL)
                if new and enrol:
                    enrol(new)
            self._write_outcome(t, input, repair)
            if writes:
                writes(new)
            if plan is not None and plan.findings:
                refusal = str(self._closer.record_refusal(plan.close.item, plan.findings))
            elif plan is not None:
                self._closer.close_in_transaction(plan.close)
                closed = True
        self._release(t.item, runs, closed)
        return CompleteResponse(next_step=new, teardown_refusal=refusal)

    def _write_outcome(self, t, input: CompleteInput, repair):
        marker = "outcome: %s" % input.outcome
        current = self._store.get_node(t.id)
        if not repair or marker not in (current.notes or "").splitlines():
            self._store.note(t.id, marker)
        if input.note and (not repair or not current.report):
            self._store.set_report(t.id, input.note)

    def _release(self, item, runs, closed):
        if self._worktrees is None:
            return
        released = self._passes.release_runs(runs, self._worktrees)
        if closed:
            self._closer.release(item)
        elif runs and released:
            self._store.label_remove(item, RELEASE_PENDING_LABEL)

    def _close_plan(self, t, creates_next):
        if creates_next or not t.item:
            return None
        node = self._store.get_node(t.item)
        if node.type != "item":
            return None
        if any(c.state != State.DONE for c in self._store.children(t.item) if c.id != t.id):
            return None
        close = CloseItemInput(item=t.item, reason=_AUTO_CLOSE_REASON, disposition="completed")
        return ClosePlan(close=close, findings=tuple(self._closer.teardown_findings(close)))

    def _complete_workflow(self, t, input: CompleteInput, repair) -> CompleteResponse:
        name = self._flow.workflow_for(t)
        if repair:
            return self._complete(
                t, input, writes=self._workflow_writes(t, input, None, True), repair=True)
        transition = self._resolver.resolve(t, input.outcome, name)
        declared = self._flow.outcomes_for(t.stage, name)
        if transition is None and declared and input.outcome not in declared:
            raise UseCaseError(
                "no transition for step=%s outcome=%s; not closing. "
                "Fix the flow or use a defined outcome." % (t.stage, input.outcome)
            )
        if transition is None and not self._flow.step_declared(t.stage, name):
            decision = (
                "no transition for step=%s outcome=%s; the workflow does not define %s"
                % (t.stage, input.outcome, t.stage)
            )
            observation = (
                "step '%s' completed with outcome '%s', but workflow '%s' has no route "
                "defined for it" % (t.stage, input.outcome, name)
            )
            ParkStepUseCase(self._store).execute(
                ParkInput(step=input.step, observation=observation, decision=decision)
            )
            return CompleteResponse(next_step=None)
        target = (
            StepContract.from_meta(self._flow.meta_for_step(transition.to_stage, name))
            if transition
            else None
        )
        missing = StepContract.from_meta(
            self._flow.meta_for_step(t.stage, name)
        ).missing_outputs(
            self._outputs.present_types(t), target
        )
        if missing:
            raise UseCaseError(
                "cannot close %s: step '%s' must produce %s; none on the item. "
                "lc link the artifact first." % (input.step, t.stage, ", ".join(sorted(missing)))
            )
        ends_pass = self._passes.ends_pass(t.stage, input.outcome, name)
        if ends_pass:
            findings = self._passes.release_refusals(t.item, self._worktrees)
            if findings:
                return self._refuse_pass_end(t, input, findings)
        spec = self._resolver.spec_for(t, transition)

        def enrol(new):
            if transition:
                self._passes.enrol(t.item, new, transition.to_stage, name)

        return self._complete(
            t, input, spec=spec, ends_pass=ends_pass, enrol=enrol,
            writes=self._workflow_writes(t, input, transition),
        )

    def _workflow_writes(self, t, input: CompleteInput, transition, repair=False):
        def writes(new):
            ScheduleCompletion(self._store, self._flow).execute(t, input.outcome)
            if repair:
                target = self._human_successor(t)
            elif new and transition and transition.to_role == "human":
                target = new
            else:
                target = None
            if target is not None and self._store.step_inputs(target) is None:
                self._inputs.freeze(self._store.get_node(target))

        return writes

    def _human_successor(self, t):
        return next(
            (c.id for c in self._store.children(t.item)
             if c.previous_step == t.id and c.role == "human" and c.state != State.DONE),
            None,
        )

    def _refuse_pass_end(self, t, input: CompleteInput, findings) -> CompleteResponse:
        text = "; ".join(findings)
        ParkStepUseCase(self._store).execute_once(
            ParkInput(
                step=input.step,
                observation="pass end refused: %s" % text,
                decision=(
                    "commit, push or discard the work named, then run lc done %s %s again"
                    % (input.step, input.outcome)
                ),
            )
        )
        message = (
            "cannot end the pass for %s: %s. Commit, push or discard that work, "
            "then complete %s again." % (t.item, text, input.step)
        )
        return CompleteResponse(next_step=None, teardown_refusal=message)

    def _complete_engine_audit(
        self, t, input: CompleteInput, mark_retroed: bool, repair,
    ) -> CompleteResponse:
        spec = None
        if input.outcome == "findings" and input.note and not repair:
            spec = NodeSpec(stage=FINDINGS_STEP, role="human", item=t.item, previous=t.id)

        def writes(fid):
            if mark_retroed:
                self._mark_retroed()
            if fid is not None:
                self._store.note(fid, "findings: lc show %s" % input.step)
                self._store.note(fid, input.note)

        resp = self._complete(t, input, spec=spec, writes=writes, repair=repair)
        return CompleteResponse(next_step=None, teardown_refusal=resp.teardown_refusal)

    def _day_summary_writes(self, t, input: CompleteInput):
        def writes(_new):
            day = self._store.summary_day_for_step(t.id)
            if day is None:
                return
            row = self._store.day_summary(day)
            if input.outcome == "done":
                text = next(
                    (a.value for a in self._store.item_artifacts(t.id) if a.type == "summary"),
                    None,
                )
                current = closed_count(self._store, day)
                self._store.finish_day_summary(
                    day, summary=text, summarized_count=row.spawn_count,
                    clear_dirty=(current == row.spawn_count),
                )
            else:
                self._store.release_day_summary(day)

        return writes

    def _mark_retroed(self):
        for item in self._store.closed_unretroed_items():
            if has_feedback(self._store, item):
                self._store.label_add(item.id, RETROED_LABEL)
        for pass_record in self._store.closed_unretroed_passes():
            if pass_reflection_count(self._store, pass_record) > 0:
                self._store.label_add(pass_record.id, RETROED_LABEL)
