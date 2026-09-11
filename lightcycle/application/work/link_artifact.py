from dataclasses import dataclass
from typing import Optional

from lightcycle.application.errors import UseCaseError
from lightcycle.application.setup.project_registry import ProjectRegistry
from lightcycle.domain.runs import RUN_FIELDS
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


class LinkArtifactUseCase:
    def __init__(self, store, flow=None):
        self._store = store
        self._flow = flow

    def execute(self, input: LinkArtifactInput) -> None:
        if input.value == "":
            raise UseCaseError(
                "empty value for '%s' on '%s' is refused - attach has no way to store or "
                "clear a blank artifact" % (input.atype, input.item)
            )
        if self._store.default_kind_for(input.atype) == "filepath":
            self._validate_spec(input.item, input.value)
        if input.atype in RUN_FIELDS:
            self._route_to_run(input)
            return
        if input.replace:
            self._store.replace_artifact(
                input.item, input.atype, input.value, input.label,
                internal=input.internal, kind=input.kind,
            )
        else:
            self._refuse_if_duplicate(input)
            self._store.add_artifact(
                input.item, input.atype, input.value, input.label,
                internal=input.internal, kind=input.kind,
            )

    def _refuse_if_duplicate(self, input):
        exists = any(
            a.type == input.atype and a.label == input.label
            for a in self._store.item_artifacts(input.item)
        )
        if exists:
            labeled = " labeled '%s'" % input.label if input.label else ""
            raise UseCaseError(
                "'%s' already has a '%s' artifact%s - pass --replace to overwrite it, "
                "or a different --label to attach another"
                % (input.item, input.atype, labeled)
            )

    def _route_to_run(self, input):
        node = self._store.get_node(input.item)
        if node.type == "step":
            raise UseCaseError(
                "'%s' is a step; '%s' attaches to an item's open phase run - pass the item id"
                % (input.item, input.atype)
            )
        if node.type != "item":
            raise UseCaseError("'%s' is not an item (type=%s)" % (input.item, node.type))
        run = self._current_run(input.item)
        if run is None:
            raise UseCaseError(
                "item '%s' has no open phase run to attach '%s' to" % (input.item, input.atype)
            )
        if input.atype == "pr":
            self._set_pr(run, input.value)
        elif input.atype == "branch":
            self._store.set_branch(run.id, input.value)
        else:
            self._store.set_comments_handled_through(run.id, input.value)

    def _set_pr(self, run, value):
        if run.pr != value:
            self._store.record_pr_pin(run.id, value, None)
        else:
            self._store.set_pr(run.id, value)

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
        registry = ProjectRegistry(self._store)
        try:
            repo_project = registry.find(repo_value)
        except ProjectResolutionError:
            return None
        try:
            leading_project = registry.find(leading)
        except ProjectResolutionError:
            return "leading directory '%s' is not a registered project (item's repo project is '%s')" % (
                leading, repo_project.identity,
            )
        if leading_project.identity != repo_project.identity:
            return "leading directory '%s' resolves to project '%s', not the item's repo project '%s'" % (
                leading, leading_project.identity, repo_project.identity,
            )
        return None
