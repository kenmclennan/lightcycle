"""MonitorMergedPrs: detect merged PRs and close their stories.

Each call scans open tasks whose flow step declares on_pr_merge, checks their
story's PR artifact against GitHub, and closes any whose PR has been merged.
The close reason is the declared on_pr_merge outcome - no hardcoded strings.
The watch set is re-derived from the store each call - no persistent poll
registry - so a restart mid-wait picks up the merge on the next tick.
"""
from dataclasses import dataclass
from typing import List

from the_grid.application.work.close_story import CloseStoryInput, CloseStoryUseCase
from the_grid.domain.work.status import Status


@dataclass(frozen=True)
class MonitorMergedPrsResponse:
    merged: List[str]


class MonitorMergedPrsUseCase:

    def __init__(self, store, github, worktrees, flow):
        self._store = store
        self._github = github
        self._worktrees = worktrees
        self._flow = flow

    def execute(self) -> MonitorMergedPrsResponse:
        merged = []
        close = CloseStoryUseCase(self._store, self._worktrees)
        for task in self._store.all_tasks():
            if task.type != "task" or task.status == Status.DONE:
                continue
            outcome = self._flow.pr_merge_outcome(task.step)
            if outcome is None:
                continue
            if not task.parent:
                continue
            pr = next((a for a in self._store.story_artifacts(task.parent) if a.type == "pr"), None)
            if pr is None:
                continue
            if self._github.is_merged(pr.value):
                close.execute(CloseStoryInput(story=task.parent, reason=outcome))
                merged.append(task.parent)
        return MonitorMergedPrsResponse(merged=merged)
