"""MonitorPrs: detect closed PRs (merged or abandoned) and close their stories;
detect /rework comments and advance the task back through the flow.

Each call scans open tasks whose flow step declares any on_pr_* hook, checks
their story's PR artifact against GitHub, and acts:
- on_pr_merge + merged PR: closes the story (M1)
- on_pr_close + unmerged-closed PR: closes the story (M2)
- on_pr_rework + open PR with /rework top-level comment since last push: advances
  the task with the declared outcome, forwarding all human comments as the note (M3)

The watch set is re-derived from the store each call - no persistent poll registry.
"""
from dataclasses import dataclass, field
from typing import List

from the_grid.application.flow.complete_task import CompleteInput
from the_grid.application.work.close_story import CloseStoryInput, CloseStoryUseCase
from the_grid.domain.work.status import Status

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


class MonitorPrsUseCase:

    def __init__(self, store, github, worktrees, flow, complete=None):
        self._store = store
        self._github = github
        self._worktrees = worktrees
        self._flow = flow
        self._complete = complete

    def execute(self) -> MonitorPrsResponse:
        merged, abandoned, reworked = [], [], []
        close = CloseStoryUseCase(self._store, self._worktrees)
        for task in self._store.all_tasks():
            if task.type != "task" or task.status == Status.DONE:
                continue
            merge_outcome = self._flow.pr_merge_outcome(task.step)
            close_outcome = self._flow.pr_close_outcome(task.step)
            rework_outcome = self._flow.pr_rework_outcome(task.step)
            if merge_outcome is None and close_outcome is None and rework_outcome is None:
                continue
            if not task.parent:
                continue
            pr = next((a for a in self._store.story_artifacts(task.parent) if a.type == "pr"), None)
            if pr is None:
                continue
            if merge_outcome and self._github.is_merged(pr.value):
                close.execute(CloseStoryInput(story=task.parent, reason=merge_outcome))
                merged.append(task.parent)
            elif close_outcome and self._github.is_closed_unmerged(pr.value):
                close.execute(CloseStoryInput(story=task.parent, reason=close_outcome))
                abandoned.append(task.parent)
            elif rework_outcome:
                since = self._github.last_push_time(pr.value)
                comments = self._github.comments_since(pr.value, since)
                human = [c for c in comments if not _is_bot(c.author)]
                top_level = [c for c in human if c.is_top_level]
                if any(_REWORK_MARKER in c.body for c in top_level):
                    guidance = _format_guidance(human)
                    self._complete.execute(
                        CompleteInput(task=task.id, outcome=rework_outcome, note=guidance or None))
                    reworked.append(task.parent)
        return MonitorPrsResponse(merged=merged, abandoned=abandoned, reworked=reworked)
