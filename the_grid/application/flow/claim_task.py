"""ClaimTask: atomically claim the next ready task for a role and build its view.

Returns the worker's claim view (the task enriched with workspace, branch, and an
absolute spec path), or None when nothing is ready or a required input is missing
(in which case the task is routed to a human).
"""
import os

from the_grid.core.contracts import required_inputs
from the_grid.core.tasks import task_from_bead


class ClaimTask:

    def __init__(self, store, flow, worktrees, workers, config):
        self._store = store
        self._flow = flow
        self._worktrees = worktrees
        self._workers = workers
        self._config = config

    def execute(self, role):
        arr = self._store.claim_ready(role)
        if not arr:
            return None
        t = task_from_bead(arr[0])
        missing = required_inputs(self._flow.meta_for_step(t["step"])) - self._store.present_types(t)
        if missing:
            self._store.route_to_human(
                t["id"],
                "BLOCKED: missing required input(s): %s" % ", ".join(sorted(missing)),
                role)
            return None
        spawnid = self._config.spawn_id()
        if spawnid:
            self._workers.stamp_bead(spawnid, t["id"])
        view = self._store.task_view(t["id"])
        story = t.get("parent") or t["id"]
        ws = self._worktrees.ensure(story)
        if ws:
            view["workspace"] = ws
        branch = self._worktrees.story_branch(story)
        if branch:
            view["branch"] = branch
        spec = next((a["value"] for a in view.get("story_artifacts", []) if a.get("type") == "spec"), None)
        if spec:
            view["spec_path"] = spec if os.path.isabs(spec) else os.path.join(self._config.specs_root(), spec)
        return view
