import os
from dataclasses import dataclass
from typing import Optional

from lightcycle.domain.contracts import StepContract
from lightcycle.domain.work import NodeView, State


@dataclass(frozen=True)
class ClaimInput:
    role: str


_STRUCTURAL_META_KEYS = ("model", "accepts", "produces")


@dataclass(frozen=True)
class ClaimResponse:
    view: NodeView
    workspace: Optional[str] = None
    branch: Optional[str] = None
    spec_path: Optional[str] = None
    brief: Optional[str] = None
    repo_path: Optional[str] = None
    config: Optional[dict] = None
    phase: Optional[str] = None
    pin: Optional[str] = None


class ClaimStepUseCase:
    def __init__(self, store, flow, worktrees, workers, config):
        self._store = store
        self._flow = flow
        self._worktrees = worktrees
        self._workers = workers
        self._config = config

    def execute(self, input: ClaimInput) -> Optional[ClaimResponse]:
        assigned = self._assigned_inflight()
        if assigned is not None:
            return self._context(assigned)
        return self._claim(input.role)

    def _assigned_inflight(self):
        spawnid = self._config.spawn_id()
        if not spawnid:
            return None
        sid = self._workers.step_for(spawnid)
        if not sid:
            return None
        try:
            node = self._store.get_node(sid)
        except KeyError:
            return None
        if node.state != State.IN_PROGRESS or node.claimed_by != spawnid:
            return None
        return node

    def _claim(self, role):
        t = self._store.claim_ready(role)
        if t is None:
            return None
        selection = self._flow.workflow_for(t)
        pin = self._flow.resolve_selection(selection) if selection else None
        meta = self._flow.meta_for_step(t.step, pin) if pin else {}
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
            self._workers.set_step(spawnid, t.id)
        try:
            return self._context(t, pin, meta)
        except Exception:
            self._store.reclaim(t.id)
            raise

    def _context(self, t, pin=None, meta=None):
        if pin is None:
            pin = self._flow.workflow_for(t)
        if meta is None:
            meta = self._flow.meta_for_step(t.step, pin) if pin else {}
        view = self._store.node_view(t.id)
        item = t.parent or t.id
        ws = self._worktrees.ensure(item)
        branch = self._worktrees.item_branch(item)
        spec = next((a.value for a in view.item_artifacts if a.type == "spec"), None)
        spec_path = None
        if spec:
            self._worktrees.sync_specs()
            spec_path = (
                spec if os.path.isabs(spec) else os.path.join(self._config.specs_root(), spec)
            )
        brief = next((a.value for a in view.item_artifacts if a.type == "brief"), None)
        repo = next((a.value for a in view.item_artifacts if a.type == "repo"), None)
        repo_path = None
        if repo:
            repo_path = (
                repo if os.path.isabs(repo) else os.path.join(self._config.projects_root(), repo)
            )
        config = {k: v for k, v in meta.items() if k not in _STRUCTURAL_META_KEYS}
        phase = self._flow.phase_for(t)
        return ClaimResponse(
            view=view, workspace=ws, branch=branch, spec_path=spec_path, brief=brief,
            repo_path=repo_path, config=config or None, phase=phase, pin=pin
        )
