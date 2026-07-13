from dataclasses import dataclass, field
from typing import List

from lightcycle.application.flow.complete_step import CompleteInput
from lightcycle.application.work.close_item import CloseItemInput, CloseItemUseCase
from lightcycle.application.work.file_child_item import FileChildItemInput, FileChildItemUseCase
from lightcycle.domain.work.state import State

LC_MARKER = "<!-- lc -->"
_WATERMARK_ARTIFACT = "feedback-watermark"


def _is_bot(author):
    return "[bot]" in author


def _eligible(author, allowlist):
    return not _is_bot(author) or author in allowlist


def _thread_key(comment):
    return comment.in_reply_to_id or comment.id


def _outstanding_threads(comments):
    marked_threads = {_thread_key(c) for c in comments if LC_MARKER in c.body}
    seen, outstanding = set(), []
    for c in comments:
        if LC_MARKER in c.body:
            continue
        key = _thread_key(c)
        if key is None or key in marked_threads or key in seen:
            continue
        seen.add(key)
        outstanding.append(c)
    return outstanding


def _outstanding_reviews(reviews, comments):
    marked_at = sorted(c.created_at for c in comments if LC_MARKER in c.body)
    outstanding = []
    for r in reviews:
        if LC_MARKER in r.body:
            continue
        if any(ts > r.created_at for ts in marked_at):
            continue
        outstanding.append(r)
    return outstanding


def _watermark(artifacts):
    watermark = next((a for a in artifacts if a.type == _WATERMARK_ARTIFACT), None)
    if watermark is None:
        return 0.0
    try:
        return float(watermark.value)
    except (TypeError, ValueError):
        return 0.0


@dataclass(frozen=True)
class MonitorPrsResponse:
    merged: List[str]
    abandoned: List[str] = field(default_factory=list)
    reworked: List[str] = field(default_factory=list)
    conflicted: List[str] = field(default_factory=list)


class MonitorPrsUseCase:
    def __init__(self, store, github, worktrees, flow_service, complete=None):
        self._store = store
        self._github = github
        self._worktrees = worktrees
        self._flow_service = flow_service
        self._complete = complete

    def _flow_for(self, node):
        name = self._flow_service.workflow_for(node)
        project = self._flow_service.project_for(node)
        return self._flow_service.load_flow(name, project)

    def execute(self) -> MonitorPrsResponse:
        merged, abandoned, reworked, conflicted = [], [], [], []
        close = CloseItemUseCase(self._store, self._worktrees)
        file_child = FileChildItemUseCase(self._store, self._flow_service)
        for item in self._store.all_nodes():
            if item.type != "item":
                continue
            pr = next((a for a in self._store.item_artifacts(item.id) if a.type == "pr"), None)
            if pr is None:
                continue
            flow = self._flow_for(item)
            merge_outcome = flow.terminal_merge_outcome()
            close_outcome = flow.terminal_close_outcome()
            if merge_outcome and self._github.is_merged(pr.value):
                close.execute(CloseItemInput(item=item.id, reason=merge_outcome))
                merged.append(item.id)
                target = flow.files_item_target(merge_outcome)
                if target:
                    workflow, step = target
                    file_child.execute(
                        FileChildItemInput(parent=item.id, workflow=workflow, step=step)
                    )
            elif close_outcome and self._github.is_closed_unmerged(pr.value):
                close.execute(CloseItemInput(item=item.id, reason=close_outcome))
                abandoned.append(item.id)
        for step in self._store.all_nodes():
            if step.type != "step" or step.state == State.DONE:
                continue
            if not step.parent:
                continue
            flow = self._flow_for(step)
            feedback_step = flow.pr_feedback_step(step.step)
            conflict_outcome = flow.pr_conflict_outcome(step.step)
            if feedback_step is None and conflict_outcome is None:
                continue
            pr = next((a for a in self._store.item_artifacts(step.parent) if a.type == "pr"), None)
            if pr is None:
                continue
            advanced = False
            if feedback_step and self._has_outstanding_feedback(step, pr.value, flow):
                advanced = True
                already_open = any(
                    n.type == "step" and n.step == feedback_step and n.parent == step.parent
                    for n in self._store.all_nodes()
                )
                if not already_open:
                    role = flow.owner_of(feedback_step)
                    title = self._store.get_node(step.parent).title
                    tid = self._store.create_step(
                        "%s: %s" % (feedback_step, title), step=feedback_step,
                        role=role, parent=step.parent,
                    )
                    self._store.add_artifact(tid, "watched-step", step.id)
                    reworked.append(step.parent)
            if not advanced and conflict_outcome and self._github.is_conflicted(pr.value):
                cap = flow.pr_conflict_cap(step.step)
                esc = flow.pr_conflict_escalate(step.step)
                if cap is not None and esc:
                    prior = sum(1 for t in self._store.steps_at_step(step.step)
                                if t.parent == step.parent
                                and t.state == State.DONE and t.outcome == conflict_outcome)
                    outcome = esc if prior >= cap else conflict_outcome
                else:
                    outcome = conflict_outcome
                self._complete.execute(CompleteInput(step=step.id, outcome=outcome))
                conflicted.append(step.parent)
        return MonitorPrsResponse(
            merged=merged, abandoned=abandoned, reworked=reworked, conflicted=conflicted
        )

    def _has_outstanding_feedback(self, step, pr, flow):
        since = self._github.last_push_time(pr)
        top_level = self._github.comments_since(pr, since)
        inline = self._github.pull_comments(pr, since)
        reviews = self._github.reviews(pr, since)

        allowlist = flow.review_bot_allowlist(step.step)
        eligible_threads = [
            c for c in _outstanding_threads(inline) if _eligible(c.author, allowlist)
        ]
        if eligible_threads:
            return True

        eligible_reviews = [
            r for r in _outstanding_reviews(reviews, top_level + inline)
            if r.author in allowlist
        ]
        if eligible_reviews:
            return True

        mention_token = flow.mention_token(step.step)
        if mention_token:
            watermark = _watermark(self._store.item_artifacts(step.id))
            mentions = [
                c for c in top_level
                if LC_MARKER not in c.body and not _is_bot(c.author)
                and mention_token in c.body and c.created_at > watermark
            ]
            if mentions:
                return True

        return False
