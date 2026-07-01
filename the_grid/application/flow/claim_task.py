"""ClaimTask: atomically claim the next ready task for a role and build its view.

Returns the worker's claim view (the task enriched with workspace, branch, and an
absolute spec path), or None when nothing is ready or a required input is missing
(in which case the task is routed to a human).
"""
import os
from dataclasses import dataclass
from typing import Optional

from the_grid.domain.contracts import StepContract


@dataclass(frozen=True)
class ClaimInput:
    role: str


@dataclass(frozen=True)
class ClaimResponse:
    view: dict


class ClaimTaskUseCase:

    def __init__(self, store, flow, worktrees, workers, config):
        self._store = store
        self._flow = flow
        self._worktrees = worktrees
        self._workers = workers
        self._config = config

    def execute(self, input: ClaimInput) -> Optional[ClaimResponse]:
        role = input.role
        t = self._store.claim_ready(role)
        if t is None:
            return None
        missing = StepContract.from_meta(self._flow.meta_for_step(t.step)).missing_inputs(
            self._store.present_types(t))
        if missing:
            self._store.route_to_human(
                t.id, "BLOCKED: missing required input(s): %s" % ", ".join(sorted(missing)))
            return None
        spawnid = self._config.spawn_id()
        if spawnid:
            self._workers.stamp_bead(spawnid, t.id)
        view = self._store.task_view(t.id)
        story = t.parent or t.id
        ws = self._worktrees.ensure(story)
        if ws:
            view["workspace"] = ws
        branch = self._worktrees.story_branch(story)
        if branch:
            view["branch"] = branch
        spec = next((a["value"] for a in view.get("story_artifacts", []) if a.get("type") == "spec"), None)
        if spec:
            view["spec_path"] = spec if os.path.isabs(spec) else os.path.join(self._config.specs_root(), spec)
        return ClaimResponse(view=view)
