from dataclasses import dataclass, field
from typing import List, Optional

from lightcycle.application.errors import UseCaseError
from lightcycle.application.work.project_clone import ensure_project_cloned
from lightcycle.application.work.stack_runs import StackRuns
from lightcycle.application.work.step_filing import check_step_filing, file_step
from lightcycle.domain.work import State


@dataclass(frozen=True)
class ActivateItemInput:
    item: str
    workflow: Optional[str] = None
    step: Optional[str] = None
    deps: List[str] = field(default_factory=list)
    stacks_on: Optional[str] = None


@dataclass(frozen=True)
class ActivateItemResponse:
    step: str


class ActivateItemUseCase:
    def __init__(self, store, flow, git, config, scaffold=None):
        self._store = store
        self._flow = flow
        self._git = git
        self._config = config
        self._scaffold = scaffold

    def _stack_deps(self, item_id, parent_id):
        if parent_id == item_id:
            raise UseCaseError("item '%s' cannot stack on itself" % item_id)
        parent = self._store.get_item(parent_id)
        if parent.state == State.DONE:
            raise UseCaseError(
                "cannot stack '%s' on '%s': the parent is %s" % (item_id, parent_id, parent.state)
            )
        if not parent.workflow:
            raise UseCaseError(
                "cannot stack '%s' on '%s': the parent has not been activated; activate the "
                "parent first" % (item_id, parent_id)
            )
        stack_runs = StackRuns(self._store, self._flow)
        if not stack_runs.has_phase(parent_id):
            raise UseCaseError(
                "cannot stack '%s' on '%s': its workflow %s has no phase in the project repo "
                "to stack on" % (item_id, parent_id, parent.workflow)
            )
        repo = self._store.get_item(item_id).repo
        if parent.repo != repo:
            raise UseCaseError(
                "cannot stack '%s' (repo %s) on '%s' (repo %s): a branch cannot be based on "
                "one repo's head in another" % (item_id, repo, parent_id, parent.repo)
            )
        run = stack_runs.run_of(parent_id)
        return [] if run is not None and run.pr else [parent_id]

    def execute(self, input: ActivateItemInput) -> ActivateItemResponse:
        node = self._store.get_node(input.item)
        if node.type != "item":
            raise UseCaseError("'%s' is not an item (type=%s)" % (input.item, node.type))
        if node.state != State.BACKLOGGED:
            raise UseCaseError("item '%s' is not a todo (state=%s)" % (input.item, node.state))
        item_id = input.item
        selection = input.workflow
        if selection is None:
            selection = self._flow.inherited_selection(node)
        if selection is None:
            raise UseCaseError(
                "no workflow selected for '%s'; pass --workflow <origin>/<name>" % input.item)
        try:
            pin = self._flow.resolve_selection(selection)
            self._flow.load_graph(pin)
        except ValueError as e:
            raise UseCaseError(str(e))
        step_name, role = check_step_filing(self._store, self._flow, item_id, pin, input.step)
        deps = list(input.deps)
        if input.stacks_on:
            deps = self._stack_deps(item_id, input.stacks_on)
        repo = self._store.get_item(item_id).repo
        ensure_project_cloned(self._store, self._git, self._config, repo, self._scaffold)
        self._store.edit_node(item_id, workflow=pin)
        if input.stacks_on:
            self._store.set_stacks_on(item_id, input.stacks_on)
        step = file_step(self._store, self._flow, item_id, pin, step_name, role, deps=deps)
        return ActivateItemResponse(step=step)
