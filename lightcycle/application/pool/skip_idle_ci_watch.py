from lightcycle.application.flow.complete_step import CompleteInput
from lightcycle.application.pool.pr_lookups import flow_for, run_of
from lightcycle.config import ConfigError
from lightcycle.application.pool.feedback_window import (
    already_admitted_keys,
    feedback_stage_of,
    feedback_window_start,
)
from lightcycle.domain.feedback import hold_key, roles_of, routed
from lightcycle.domain.flow.step_def import SKIP_OUTCOME
from lightcycle.domain.work import State
from lightcycle.ports.github import ReadFailure


class SkipIdleCiWatchUseCase:
    def __init__(self, store, github, flow_service, complete, *, trusted_authors, review_bots):
        self._store = store
        self._github = github
        self._flow_service = flow_service
        self._complete = complete
        self._trusted_authors = trusted_authors
        self._review_bots = review_bots

    def _skippable(self, step):
        if step is None or step.type != "step":
            return False
        if step.state != State.QUEUED or step.claimed_by:
            return False
        sd = flow_for(self._flow_service, step).step_def(step.stage)
        return sd.owner == "agent" and not sd.always_run and SKIP_OUTCOME in sd.routes

    def _cutoff_if_idle(self, run, pr, flow, poll_step):
        last_push = self._github.last_push_time(pr)
        if isinstance(last_push, ReadFailure):
            return None
        since = feedback_window_start(run, last_push)
        top_level = self._github.comments_since(pr, since)
        inline = self._github.pull_comments(pr, since)
        reviews = self._github.reviews(pr, since)
        if any(isinstance(r, ReadFailure) for r in (top_level, inline, reviews)):
            return None
        try:
            roles = roles_of(self._trusted_authors(), self._review_bots())
        except ConfigError:
            return None
        step_def = feedback_stage_of(flow, poll_step)
        mention_token = step_def.mention_token if step_def else None
        routes = routed(top_level, inline, reviews, roles, mention_token)
        already = (
            already_admitted_keys(self._store, step_def.pr_feedback, poll_step.item)
            if step_def else set()
        )
        for kind, items in (
            ("inline", routes.inline), ("review", routes.review), ("mention", routes.mention),
        ):
            if any(hold_key(kind, i.id) not in already for i in items):
                return None
        if self._store.approved_holds(run.id):
            return None
        return since

    def execute(self, poll_step, next_step_id, pr, sha):
        step = self._store.get_node(next_step_id)
        if not self._skippable(step):
            return False
        run = run_of(self._store, self._flow_service, step)
        if run is None or run.pr != pr:
            return False
        if self._github.head_sha(pr) != sha:
            return False
        since = self._cutoff_if_idle(run, pr, flow_for(self._flow_service, poll_step), poll_step)
        if since is None:
            return False
        note = (
            "Skipped by the engine: CI succeeded on %s and PR %s has no comment, inline thread "
            "or review that routes newer than the feedback cutoff %s, and no approved "
            "held comment. No agent ran." % (sha, pr, since)
        )
        self._complete.execute(CompleteInput(step=next_step_id, outcome=SKIP_OUTCOME, note=note))
        return True
