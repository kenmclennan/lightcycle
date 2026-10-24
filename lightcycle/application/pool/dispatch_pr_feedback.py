from dataclasses import dataclass, field
from typing import List

from lightcycle.application.flow.complete_step import CompleteInput
from lightcycle.application.flow.escapes import EscapeRecorder
from lightcycle.application.pool.pr_lookups import (
    _MIN_TIMESTAMP,
    flow_for,
    run_of,
    skip_unpinned,
)
from lightcycle.application.pool.pr_sync_reads import PrSyncReads
from lightcycle.application.feedback.hold_comment import HoldCommentUseCase
from lightcycle.config import ConfigError
from lightcycle.domain.feedback import (
    ADMIT,
    LC_MARKER,
    HeldComment,
    hold_key,
    outstanding_reviews,
    outstanding_threads,
    standing,
)
from lightcycle.domain.flow import outcome_counts, pr_conflict_failures, total_outcome_count
from lightcycle.domain.flow.hooks import PR_CONFLICT_CAP
from lightcycle.domain.work import State, node_id_key, parse_timestamp
from lightcycle.ports.github import NotYetRead, ReadFailure

CONFLICT_BASE_TIP = "conflict-base-tip"


@dataclass(frozen=True)
class DispatchPrFeedbackResponse:
    reworked: List[str] = field(default_factory=list)
    conflicted: List[str] = field(default_factory=list)


def _epoch(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _is_conflicted(sync):
    return not isinstance(sync, ReadFailure) and sync.conflicted


@dataclass(frozen=True)
class _Feedback:
    admitted: List[HeldComment] = field(default_factory=list)
    approved: List[HeldComment] = field(default_factory=list)
    cutoff: float = 0.0

    def __bool__(self):
        return bool(self.admitted or self.approved)


def _candidate(run, kind, obj, path=None, line=None):
    return HeldComment(
        run_id=run.id, key=hold_key(kind, obj.id), author=obj.author, body=obj.body,
        created_at=obj.created_at, path=path, line=line,
    )


class DispatchPrFeedbackUseCase:
    def __init__(self, store, github, flow_service, complete, *, trusted_authors, held_shortcode):
        self._store = store
        self._github = github
        self._flow_service = flow_service
        self._complete = complete
        self._trusted_authors = trusted_authors
        self._hold = HoldCommentUseCase(store, held_shortcode)
        self._escapes = EscapeRecorder(store)

    def _note_gh_read_failure(self, step_id, failure):
        if isinstance(failure, NotYetRead):
            return
        self._store.note_condition(
            step_id,
            "gh read failed while checking outstanding feedback (exit %d): %s"
            % (failure.returncode, failure.stderr),
        )

    def _keyed(self, step, run, kind, items):
        keyed = []
        for obj in items:
            if obj.id is None:
                self._store.note_condition(
                    step.id,
                    "a %s from %s has no id, so it is neither held nor admitted"
                    % (kind, obj.author),
                )
                continue
            keyed.append(_candidate(run, kind, obj, getattr(obj, "path", None),
                                    getattr(obj, "line", None)))
        return keyed

    def _outstanding_feedback(self, step, pr, flow, run):
        since = self._github.last_push_time(pr)
        if isinstance(since, ReadFailure):
            self._note_gh_read_failure(step.id, since)
            return _Feedback()
        top_level = self._github.comments_since(pr, since)
        inline = self._github.pull_comments(pr, since)
        reviews = self._github.reviews(pr, since)
        failure = next(
            (r for r in (top_level, inline, reviews) if isinstance(r, ReadFailure)), None
        )
        if failure is not None:
            self._note_gh_read_failure(step.id, failure)
            return _Feedback()

        try:
            trusted = self._trusted_authors()
        except ConfigError as e:
            self._store.note_condition(
                step.id, "feedback not read: config key trusted-authors is unset (%s)" % e)
            return _Feedback()

        step_def = flow.step_def(step.stage)
        mention_token = step_def.mention_token

        def admits(item):
            return standing(item.author, trusted) == ADMIT

        unmarked = [c for c in inline if LC_MARKER not in c.body]
        mentions = [
            c for c in top_level
            if mention_token and LC_MARKER not in c.body and mention_token in c.body
        ]
        signalled = outstanding_reviews(reviews, inline, mention_token)

        dispatched_through = _epoch(run.comments_dispatched_through)
        admitted = []
        for kind, items in (
            ("inline", outstanding_threads([c for c in inline if admits(c)])),
            ("review", [r for r in signalled if admits(r)]),
            ("mention", [c for c in mentions if admits(c)]),
        ):
            admitted += self._keyed(
                step, run, kind, [i for i in items if i.created_at > dispatched_through])

        origin = self._store.get_item(step.item)
        for kind, items in (
            ("inline", [c for c in unmarked if not admits(c)]),
            ("review", [r for r in signalled if not admits(r)]),
            ("mention", [c for c in mentions if not admits(c)]),
        ):
            for held in self._keyed(step, run, kind, items):
                self._hold.execute(run, origin, pr, held)

        return _Feedback(
            admitted=admitted, approved=self._store.approved_holds(run.id), cutoff=since)

    def _open_feedback_step(self, step, flow, feedback_step, run, outstanding):
        with self._store.transaction():
            role = flow.step_def(feedback_step).owner
            tid = self._store.create_step(stage=feedback_step, role=role, item=step.item)
            self._store.set_watched_step(tid, step.id)
            comments = outstanding.admitted + outstanding.approved
            keys = [h.key for h in comments]
            self._store.add_artifact(tid, "admitted-comments", "\n".join(keys), internal=True)
            self._store.add_artifact(
                tid, "feedback-cutoff", str(outstanding.cutoff), internal=True)
            for held in outstanding.approved:
                self._store.mark_hold_dispatched(run.id, held.key)
            if outstanding.admitted:
                newest = max(h.created_at for h in outstanding.admitted)
                self._store.set_comments_dispatched_through(run.id, str(newest))
            self._escapes.record_pr_comment(
                flow, tid, step.item, run, keys, [h.author for h in comments],
                self._trusted_authors())

    def _recorded_tip(self, step_id):
        found = None
        for artifact in self._store.item_artifacts(step_id):
            if artifact.type == CONFLICT_BASE_TIP:
                found = artifact.value
        return found

    def _read_base_tip(self, step, sync):
        repo, _, base = sync.base_key.partition("@")
        tip = self._github.branch_tip(repo, base)
        if isinstance(tip, ReadFailure) or not tip:
            return None
        self._store.add_artifact(step.id, CONFLICT_BASE_TIP, tip, internal=True)
        return tip

    def _escalated_resolutions(self, step, flow, conflict_outcome):
        gate = flow.step_def(step.stage)
        resolve_stage = gate.routes.get(conflict_outcome)
        escalate_outcome = next(
            (c.escalate_outcome for c in gate.caps.values()
             if c.outcome == conflict_outcome and c.escalate_outcome),
            None,
        )
        escalation = gate.routes.get(escalate_outcome)
        if not resolve_stage or not escalation:
            return 0
        resolve_routes = flow.step_def(resolve_stage).routes
        return sum(
            1 for t in self._store.steps_at_step(resolve_stage)
            if t.item == step.item and t.state == State.DONE
            and resolve_routes.get(t.outcome) == escalation
        )

    def _conflict_cap_note(self, fired, failures, prior, stage, step_id):
        resolve = "rebase the branch onto main, resolve, push, then `lc done %s resolved`" % step_id
        if fired == PR_CONFLICT_CAP:
            return "%s reached: %d failed resolutions in %d conflicts at %s; %s" % (
                fired, failures, prior + 1, stage, resolve)
        return "%s reached: %d conflicts (%d failed resolutions) at %s; %s" % (
            fired, prior + 1, failures, stage, resolve)

    def execute(self, reads=None) -> DispatchPrFeedbackResponse:
        reads = reads or PrSyncReads(self._github)
        reworked, conflicted = [], []
        for step in self._store.all_nodes():
            if step.type != "step" or step.state == State.DONE:
                continue
            if not step.item:
                continue
            if skip_unpinned(self._store, self._flow_service, step):
                continue
            flow = flow_for(self._flow_service, step)
            feedback_step = flow.step_def(step.stage).pr_feedback
            conflict_outcome = flow.step_def(step.stage).pr_conflict
            if feedback_step is None and conflict_outcome is None:
                continue
            run = run_of(self._store, self._flow_service, step)
            pr_value = run.pr if run else None
            if pr_value is None:
                continue
            advanced = False
            if feedback_step:
                outstanding = self._outstanding_feedback(step, pr_value, flow, run)
                if outstanding:
                    advanced = True
                    open_now = any(
                        n.type == "step" and n.stage == feedback_step and n.item == step.item
                        for n in self._store.all_nodes()
                    )
                    if not open_now:
                        self._open_feedback_step(step, flow, feedback_step, run, outstanding)
                        reworked.append(step.item)
            sync = reads.read(pr_value) if not advanced and conflict_outcome else None
            if sync is not None and _is_conflicted(sync):
                history = [t for t in self._store.steps_at_step(step.stage)
                           if t.item == step.item and t.state == State.DONE]
                conflicts = sorted(
                    (t for t in history if t.outcome == conflict_outcome),
                    key=lambda t: (parse_timestamp(t.created_at) or _MIN_TIMESTAMP,
                                   node_id_key(t.id)),
                )
                prior = total_outcome_count(history, conflict_outcome)
                current_tip = self._read_base_tip(step, sync)
                failures = pr_conflict_failures(
                    [self._recorded_tip(t.id) for t in conflicts],
                    current_tip,
                    self._escalated_resolutions(step, flow, conflict_outcome),
                )
                counts = outcome_counts(history, conflict_outcome, failures)
                fired = flow.fired_cap(step.stage, conflict_outcome, counts)
                outcome = flow.escalated_outcome(step.stage, conflict_outcome, counts)
                done = self._complete.execute(CompleteInput(step=step.id, outcome=outcome))
                if fired is not None and done.next_step:
                    self._store.note_condition(
                        done.next_step,
                        self._conflict_cap_note(fired.hook, failures, prior, step.stage, done.next_step),
                    )
                conflicted.append(step.item)
        return DispatchPrFeedbackResponse(reworked=reworked, conflicted=conflicted)
