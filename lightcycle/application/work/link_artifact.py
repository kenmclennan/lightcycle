from dataclasses import dataclass
from typing import Optional

from lightcycle.application.errors import UseCaseError
from lightcycle.domain.work.item import Item
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
    def __init__(self, store):
        self._store = store

    def execute(self, input: LinkArtifactInput) -> None:
        if input.atype == "spec":
            self._validate_spec(input.item, input.value)
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
        repo_value = Item(item, tuple(self._store.item_artifacts(item))).repo()
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
