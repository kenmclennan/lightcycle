from dataclasses import dataclass, field
from typing import List

from lightcycle.application.flow.complete_step import CompleteInput
from lightcycle.application.pool.pr_lookups import flow_for, run_of, skip_unpinned
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
from lightcycle.domain.flow import total_outcome_count
from lightcycle.domain.work import State
from lightcycle.ports.github import NotYetRead, ReadFailure


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

        return _Feedback(admitted=admitted, approved=self._store.approved_holds(run.id))

    def _open_feedback_step(self, step, flow, feedback_step, run, outstanding):
        role = flow.step_def(feedback_step).owner
        tid = self._store.create_step(step=feedback_step, role=role, parent=step.item)
        self._store.set_watched_step(tid, step.id)
        keys = [h.key for h in outstanding.admitted + outstanding.approved]
        self._store.add_artifact(tid, "admitted-comments", "\n".join(keys), internal=True)
        for held in outstanding.approved:
            self._store.mark_hold_dispatched(run.id, held.key)
        if outstanding.admitted:
            newest = max(h.created_at for h in outstanding.admitted)
            self._store.set_comments_dispatched_through(run.id, str(newest))

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
            if not advanced and conflict_outcome and _is_conflicted(reads.read(pr_value)):
                history = [t for t in self._store.steps_at_step(step.stage)
                           if t.item == step.item and t.state == State.DONE]
                prior = total_outcome_count(history, conflict_outcome)
                outcome = flow.pr_conflict_transition(step.stage, conflict_outcome, prior)
                done = self._complete.execute(CompleteInput(step=step.id, outcome=outcome))
                if outcome != conflict_outcome and done.next_step:
                    self._store.note_condition(
                        done.next_step,
                        "pr_conflict_cap reached: %d conflicts at %s; rebase the branch onto main, "
                        "resolve, push, then `lc done %s resolved`"
                        % (prior, step.stage, done.next_step),
                    )
                conflicted.append(step.item)
        return DispatchPrFeedbackResponse(reworked=reworked, conflicted=conflicted)
