from dataclasses import dataclass
from typing import Optional

from lightcycle.application.errors import UseCaseError
from lightcycle.domain.work import State
from lightcycle.domain.workspace.isolation import has_worktrees_component
from lightcycle.ports.store import ProjectResolutionError


@dataclass(frozen=True)
class LinkArtifactInput:
    item: str
    atype: str
    value: str
    label: Optional[str] = None
    replace: bool = False
    kind: Optional[str] = None
    internal: bool = False


_RUN_FIELDS = {
    "pr": "pr",
    "branch": "branch",
    "comments-handled": "comments_handled_through",
}


class LinkArtifactUseCase:
    def __init__(self, store, flow=None):
        self._store = store
        self._flow = flow

    def execute(self, input: LinkArtifactInput) -> None:
        if input.atype == "spec":
            self._validate_spec(input.item, input.value)
        if input.atype in _RUN_FIELDS and self._to_run(input):
            return
        if input.replace:
            self._store.replace_artifact(
                input.item, input.atype, input.value, input.label,
                internal=input.internal, kind=input.kind,
            )
        else:
            self._store.add_artifact(
                input.item, input.atype, input.value, input.label,
                internal=input.internal, kind=input.kind,
            )

    def _to_run(self, input):
        run = self._current_run(input.item)
        if run is None:
            return False
        self._store.set_run_field(run.id, **{_RUN_FIELDS[input.atype]: input.value})
        return True

    def _current_run(self, item):
        open_runs = self._store.open_runs_of(item)
        if not open_runs:
            return None
        if self._flow is None or len(open_runs) == 1:
            return open_runs[-1]
        phase = self._active_phase(item)
        return next((r for r in reversed(open_runs) if r.phase == phase), open_runs[-1])

    def _active_phase(self, item):
        for child in self._store.children(item):
            if getattr(child, "type", None) == "step" and child.state != State.DONE:
                return self._flow.phase_for(child)
        return None

    def _validate_spec(self, item, value):
        if has_worktrees_component(value):
            raise UseCaseError(
                "spec artifact '%s' points into a worktree checkout ('.worktrees' in the path) - "
                "worktrees are disposable; attach the repo-relative path in the specs repo instead"
                % value
            )
        mismatch = self._spec_project_mismatch(item, value)
        if mismatch is not None:
            raise UseCaseError("spec artifact '%s' %s" % (value, mismatch))

    def _spec_project_mismatch(self, item, value):
        leading = value.split("/", 1)[0]
        repo_value = self._store.get_item(item).repo
        if repo_value is None:
            return None
        try:
            repo_project = self._store.find_project(repo_value)
        except ProjectResolutionError:
            return None
        try:
            leading_project = self._store.find_project(leading)
        except ProjectResolutionError:
            return "leading directory '%s' is not a registered project (item's repo project is '%s')" % (
                leading, repo_project.identity,
            )
        if leading_project.identity != repo_project.identity:
            return "leading directory '%s' resolves to project '%s', not the item's repo project '%s'" % (
                leading, leading_project.identity, repo_project.identity,
            )
        return None
