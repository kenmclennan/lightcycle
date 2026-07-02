"""MonitorPrs: detect closed PRs (merged or abandoned) and close their stories.

Each call scans open tasks whose flow step declares any on_pr_* hook, checks
their story's PR artifact against GitHub, and closes any whose PR has been
merged (on_pr_merge) or closed without merging (on_pr_close). The close reason
is the declared outcome - no hardcoded strings. The watch set is re-derived from
the store each call - no persistent poll registry.
"""
from dataclasses import dataclass, field
from typing import List

from the_grid.application.work.close_story import CloseStoryInput, CloseStoryUseCase
from the_grid.domain.work.status import Status


@dataclass(frozen=True)
class MonitorPrsResponse:
    merged: List[str]
    abandoned: List[str] = field(default_factory=list)


class MonitorPrsUseCase:

    def __init__(self, store, github, worktrees, flow):
        self._store = store
        self._github = github
        self._worktrees = worktrees
        self._flow = flow

    def execute(self) -> MonitorPrsResponse:
        merged, abandoned = [], []
        close = CloseStoryUseCase(self._store, self._worktrees)
        for task in self._store.all_tasks():
            if task.type != "task" or task.status == Status.DONE:
                continue
            merge_outcome = self._flow.pr_merge_outcome(task.step)
            close_outcome = self._flow.pr_close_outcome(task.step)
            if merge_outcome is None and close_outcome is None:
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
        return MonitorPrsResponse(merged=merged, abandoned=abandoned)
