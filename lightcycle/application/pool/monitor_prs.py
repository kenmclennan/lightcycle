from dataclasses import dataclass, field
from typing import List

from lightcycle.application.flow.complete_step import CompleteInput
from lightcycle.application.work.close_item import CloseItemInput, CloseItemUseCase
from lightcycle.domain.work.state import State

LC_MARKER = "<!-- lc -->"


def _is_bot(author):
    return "[bot]" in author


def _format_guidance(comments, reviews):
    parts = []
    for c in comments:
        if c.is_top_level:
            body = c.body.strip()
            if body:
                parts.append(body)
        else:
            loc = "%s:%s" % (c.path, c.line) if c.line else (c.path or "")
            parts.append("[%s] %s" % (loc, c.body.strip()))
    for r in reviews:
        body = r.body.strip()
        if body:
            parts.append("[review by %s] %s" % (r.author, body))
    return "\n\n".join(p for p in parts if p)


@dataclass(frozen=True)
class MonitorPrsResponse:
    merged: List[str]
    abandoned: List[str] = field(default_factory=list)
    reworked: List[str] = field(default_factory=list)
    conflicted: List[str] = field(default_factory=list)


class MonitorPrsUseCase:
    def __init__(self, store, github, worktrees, flow, complete=None):
        self._store = store
        self._github = github
        self._worktrees = worktrees
        self._flow = flow
        self._complete = complete

    def execute(self) -> MonitorPrsResponse:
        merged, abandoned, reworked, conflicted = [], [], [], []
        close = CloseItemUseCase(self._store, self._worktrees)
        merge_outcome = self._flow.terminal_merge_outcome()
        close_outcome = self._flow.terminal_close_outcome()
        for item in self._store.all_nodes():
            if item.type != "item":
                continue
            pr = next((a for a in self._store.item_artifacts(item.id) if a.type == "pr"), None)
            if pr is None:
                continue
            if merge_outcome and self._github.is_merged(pr.value):
                close.execute(CloseItemInput(item=item.id, reason=merge_outcome))
                merged.append(item.id)
            elif close_outcome and self._github.is_closed_unmerged(pr.value):
                close.execute(CloseItemInput(item=item.id, reason=close_outcome))
                abandoned.append(item.id)
        for step in self._store.all_nodes():
            if step.type != "step" or step.state == State.DONE:
                continue
            rework_outcome = self._flow.pr_rework_outcome(step.step)
            conflict_outcome = self._flow.pr_conflict_outcome(step.step)
            if rework_outcome is None and conflict_outcome is None:
                continue
            if not step.parent:
                continue
            pr = next((a for a in self._store.item_artifacts(step.parent) if a.type == "pr"), None)
            if pr is None:
                continue
            advanced = False
            if rework_outcome:
                since = self._github.last_push_time(pr.value)
                comments = [
                    c for c in (
                        self._github.comments_since(pr.value, since)
                        + self._github.pull_comments(pr.value, since)
                    )
                    if LC_MARKER not in c.body
                ]
                reviews = [
                    r for r in self._github.reviews(pr.value, since)
                    if LC_MARKER not in r.body
                ]
                mention_token = self._flow.mention_token(step.step)
                allowlist = self._flow.review_bot_allowlist(step.step)
                mention = mention_token is not None and any(
                    mention_token in c.body for c in comments if not _is_bot(c.author)
                )
                botreview = any(r.author in allowlist for r in reviews)
                if mention or botreview:
                    guidance = _format_guidance(comments, reviews)
                    self._complete.execute(
                        CompleteInput(step=step.id, outcome=rework_outcome, note=guidance or None)
                    )
                    reworked.append(step.parent)
                    advanced = True
            if not advanced and conflict_outcome and self._github.is_conflicted(pr.value):
                cap = self._flow.pr_conflict_cap(step.step)
                esc = self._flow.pr_conflict_escalate(step.step)
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
