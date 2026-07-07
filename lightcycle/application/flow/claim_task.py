import os
from dataclasses import dataclass
from typing import Optional

from lightcycle.domain.contracts import StepContract
from lightcycle.domain.work import TaskView


@dataclass(frozen=True)
class ClaimInput:
    role: str


@dataclass(frozen=True)
class ClaimResponse:
    view: TaskView
    workspace: Optional[str] = None
    branch: Optional[str] = None
    spec_path: Optional[str] = None


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
        meta = self._flow.meta_for_step(
            t.step, self._flow.workflow_for(t), self._flow.project_for(t)
        )
        missing = StepContract.from_meta(meta).missing_inputs(self._store.present_types(t))
        if missing:
            self._store.route_to_human(
                t.id, "BLOCKED: missing required input(s): %s" % ", ".join(sorted(missing))
            )
            return None
        model = meta.get("model")
        if model:
            self._store.set_model(t.id, model)
        spawnid = self._config.spawn_id()
        if spawnid:
            self._workers.set_task(spawnid, t.id)
        view = self._store.task_view(t.id)
        story = t.parent or t.id
        ws = self._worktrees.ensure(story)
        branch = self._worktrees.story_branch(story)
        spec = next((a.value for a in view.story_artifacts if a.type == "spec"), None)
        spec_path = None
        if spec:
            spec_path = (
                spec if os.path.isabs(spec) else os.path.join(self._config.specs_root(), spec)
            )
        return ClaimResponse(view=view, workspace=ws, branch=branch, spec_path=spec_path)
