from dataclasses import dataclass, field
from typing import List

from lightcycle.application.flow.complete_step import CompleteInput
from lightcycle.application.pool.pr_lookups import false_on_failure, flow_for, run_of
from lightcycle.domain.feedback import (
    LC_MARKER,
    eligible,
    is_bot,
    outstanding_reviews,
    outstanding_threads,
)
from lightcycle.domain.flow import total_outcome_count
from lightcycle.domain.work import State
from lightcycle.ports.github import ReadFailure


@dataclass(frozen=True)
class DispatchPrFeedbackResponse:
    reworked: List[str] = field(default_factory=list)
    conflicted: List[str] = field(default_factory=list)


def _epoch(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


class DispatchPrFeedbackUseCase:
    def __init__(self, store, github, flow_service, complete):
        self._store = store
        self._github = github
        self._flow_service = flow_service
        self._complete = complete

    def _note_gh_read_failure(self, step_id, failure):
        self._store.note_condition(
            step_id,
            "gh read failed while checking outstanding feedback (exit %d): %s"
            % (failure.returncode, failure.stderr),
        )

    def _outstanding_feedback(self, step, pr, flow):
        since = self._github.last_push_time(pr)
        if isinstance(since, ReadFailure):
            self._note_gh_read_failure(step.id, since)
            return []
        top_level = self._github.comments_since(pr, since)
        inline = self._github.pull_comments(pr, since)
        reviews = self._github.reviews(pr, since)
        failure = next(
            (r for r in (top_level, inline, reviews) if isinstance(r, ReadFailure)), None
        )
        if failure is not None:
            self._note_gh_read_failure(step.id, failure)
            return []

        allowlist = flow.step_def(step.stage).review_bot_allowlist
        items = [c for c in outstanding_threads(inline) if eligible(c.author, allowlist)]
        items += [
            r for r in outstanding_reviews(reviews, top_level + inline) if r.author in allowlist
        ]

        mention_token = flow.step_def(step.stage).mention_token
        if mention_token:
            feedback_run = run_of(self._store, self._flow_service, step)
            watermark = _epoch(feedback_run.comments_handled_through) if feedback_run else 0.0
            items += [
                c for c in top_level
                if LC_MARKER not in c.body and not is_bot(c.author)
                and mention_token in c.body and c.created_at > watermark
            ]

        return items

    def execute(self) -> DispatchPrFeedbackResponse:
        reworked, conflicted = [], []
        for step in self._store.all_nodes():
            if step.type != "step" or step.state == State.DONE:
                continue
            if not step.item:
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
                outstanding = self._outstanding_feedback(step, pr_value, flow)
                if outstanding:
                    advanced = True
                    newest = max(o.created_at for o in outstanding)
                    open_now = any(
                        n.type == "step" and n.stage == feedback_step and n.item == step.item
                        for n in self._store.all_nodes()
                    )
                    spawned_through = _epoch(run.comments_dispatched_through) if run else 0.0
                    if not open_now and newest > spawned_through:
                        role = flow.step_def(feedback_step).owner
                        title = self._store.get_node(step.item).title
                        tid = self._store.create_step(
                            "%s: %s" % (feedback_step, title), step=feedback_step,
                            role=role, parent=step.item,
                        )
                        self._store.set_watched_step(tid, step.id)
                        if run is not None:
                            self._store.set_comments_dispatched_through(run.id, str(newest))
                        reworked.append(step.item)
            if not advanced and conflict_outcome and false_on_failure(
                self._github.is_conflicted(pr_value)
            ):
                history = [t for t in self._store.steps_at_step(step.stage)
                           if t.item == step.item and t.state == State.DONE]
                prior = total_outcome_count(history, conflict_outcome)
                outcome = flow.pr_conflict_transition(step.stage, conflict_outcome, prior)
                self._complete.execute(CompleteInput(step=step.id, outcome=outcome))
                conflicted.append(step.item)
        return DispatchPrFeedbackResponse(reworked=reworked, conflicted=conflicted)
