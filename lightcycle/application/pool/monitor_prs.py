from dataclasses import dataclass, field
from typing import List

from lightcycle.application.flow.complete_task import CompleteInput
from lightcycle.application.work.close_story import CloseStoryInput, CloseStoryUseCase
from lightcycle.domain.work.status import Status

_REWORK_MARKER = "/rework"


def _is_bot(author):
    return "[bot]" in author


def _format_guidance(comments):
    parts = []
    for c in comments:
        if c.is_top_level:
            body = c.body.replace(_REWORK_MARKER, "").strip()
            if body:
                parts.append(body)
        else:
            loc = "%s:%s" % (c.path, c.line) if c.line else (c.path or "")
            parts.append("[%s] %s" % (loc, c.body.strip()))
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
        close = CloseStoryUseCase(self._store, self._worktrees)
        merge_outcome = self._flow.terminal_merge_outcome()
        close_outcome = self._flow.terminal_close_outcome()
        for story in self._store.all_tasks():
            if story.type != "story":
                continue
            pr = next((a for a in self._store.story_artifacts(story.id) if a.type == "pr"), None)
            if pr is None:
                continue
            if merge_outcome and self._github.is_merged(pr.value):
                close.execute(CloseStoryInput(story=story.id, reason=merge_outcome))
                merged.append(story.id)
            elif close_outcome and self._github.is_closed_unmerged(pr.value):
                close.execute(CloseStoryInput(story=story.id, reason=close_outcome))
                abandoned.append(story.id)
        for task in self._store.all_tasks():
            if task.type != "task" or task.status == Status.DONE:
                continue
            rework_outcome = self._flow.pr_rework_outcome(task.step)
            conflict_outcome = self._flow.pr_conflict_outcome(task.step)
            if rework_outcome is None and conflict_outcome is None:
                continue
            if not task.parent:
                continue
            pr = next((a for a in self._store.story_artifacts(task.parent) if a.type == "pr"), None)
            if pr is None:
                continue
            advanced = False
            if rework_outcome:
                since = self._github.last_push_time(pr.value)
                comments = self._github.comments_since(pr.value, since)
                human = [c for c in comments if not _is_bot(c.author)]
                top_level = [c for c in human if c.is_top_level]
                if any(_REWORK_MARKER in c.body for c in top_level):
                    guidance = _format_guidance(human)
                    self._complete.execute(
                        CompleteInput(task=task.id, outcome=rework_outcome, note=guidance or None)
                    )
                    reworked.append(task.parent)
                    advanced = True
            if not advanced and conflict_outcome and self._github.is_conflicted(pr.value):
                cap = self._flow.pr_conflict_cap(task.step)
                esc = self._flow.pr_conflict_escalate(task.step)
                if cap is not None and esc:
                    prior = sum(1 for t in self._store.tasks_at_step(task.step)
                                if t.parent == task.parent
                                and t.status == Status.DONE and t.outcome == conflict_outcome)
                    outcome = esc if prior >= cap else conflict_outcome
                else:
                    outcome = conflict_outcome
                self._complete.execute(CompleteInput(task=task.id, outcome=outcome))
                conflicted.append(task.parent)
        return MonitorPrsResponse(
            merged=merged, abandoned=abandoned, reworked=reworked, conflicted=conflicted
        )
