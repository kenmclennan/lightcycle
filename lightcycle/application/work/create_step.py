from dataclasses import dataclass, field
from typing import List, Optional

from lightcycle.application.errors import FieldRefusalError, UseCaseError
from lightcycle.application.flow.passes import PassBook
from lightcycle.application.work.live_worker import live_claimed_step
from lightcycle.application.work.title_guard import validate_title
from lightcycle.domain.health.fork import forks, main_path_stages
from lightcycle.domain.work import State, refuse_fields
from lightcycle.ports.workers import RegistryUnreadable

_NEW_STEP = "\0new"


@dataclass(frozen=True)
class CreateStepInput:
    title: str
    step: str
    parent: str
    workflow: Optional[str] = None
    note: List[str] = field(default_factory=list)
    replace: Optional[str] = None


@dataclass(frozen=True)
class CreateStepResponse:
    id: str


class CreateStepUseCase:
    def __init__(self, store, flow, config, workers):
        self._store = store
        self._flow = flow
        self._config = config
        self._workers = workers

    def execute(self, input: CreateStepInput) -> CreateStepResponse:
        validate_title(self._config, input.title)
        if input.parent:
            try:
                owner = self._store.get_node(input.parent)
            except KeyError:
                owner = None
            if owner is not None and owner.state == State.DONE:
                raise UseCaseError(
                    "item %s is closed; use lc reopen %s to bring it back"
                    % (owner.id, owner.id)
                )
        flow = None
        pin = None
        if input.workflow:
            try:
                selected = self._flow.resolve_selection(input.workflow)
                flow = self._flow.load_flow(selected)
                pin = selected
            except (UseCaseError, ValueError) as e:
                raise UseCaseError(str(e))
        elif input.parent:
            try:
                parent = self._store.get_node(input.parent)
            except KeyError:
                raise UseCaseError("unknown parent '%s'" % input.parent)
            flow = self._flow.flow_for(parent)
            try:
                pin = self._flow.resolve_selection(parent.workflow)
            except (UseCaseError, ValueError) as e:
                raise UseCaseError(str(e))
        if flow is None or not flow.steps():
            raise UseCaseError(
                "no workflow to resolve --step against; pass --workflow <origin>/<name> "
                "or --parent <item pinned to one>"
            )
        role = flow.step_def(input.step).owner
        if not role:
            raise UseCaseError(
                "step '%s' is not owned in this workflow; owned steps: %s"
                % (input.step, ", ".join(flow.steps()) or "(none)")
            )
        if input.title.strip():
            raise FieldRefusalError(refuse_fields("step", ("title",)))
        target = self._replace_target(input)
        self._refuse_fork(input, target)
        with self._store.transaction():
            if target is not None:
                self._store.delete(target)
            tid = self._store.create_step(
                stage=input.step,
                role=role,
                item=input.parent,
                previous=self._last_closed_step(input.parent),
            )
            if input.note:
                self._store.note(tid, " ".join(input.note))
            PassBook(self._store, self._flow).enrol(input.parent, tid, input.step, pin)
        return CreateStepResponse(id=tid)

    def _replace_target(self, input):
        if not input.replace:
            return None
        try:
            node = self._store.get_node(input.replace)
        except KeyError:
            node = None
        if node is None or node.type != "step":
            raise UseCaseError("no such step: %s" % input.replace)
        if node.item != input.parent:
            raise UseCaseError(
                "step %s belongs to item %s, not %s" % (node.id, node.item, input.parent)
            )
        if node.state == State.DONE:
            raise UseCaseError("step %s is already closed; nothing to remove" % node.id)
        try:
            live = live_claimed_step(self._store, self._workers, {node.id})
        except RegistryUnreadable as e:
            raise UseCaseError(
                "refusing to replace %s: could not verify no live worker holds a claimed "
                "step - %s" % (node.id, e)
            )
        if live is not None:
            raise UseCaseError(
                "refusing to replace %s: step %s is claimed by a live worker "
                "- stop the pool or sweep first" % (node.id, live)
            )
        return node.id

    def _refuse_fork(self, input, target):
        try:
            owner = self._store.get_node(input.parent)
        except KeyError:
            return
        graph = self._flow.graph_for(owner)
        if graph is None:
            return
        open_steps = [
            (input.parent, c.id, c.stage, graph.phase_for(c.stage))
            for c in self._store.children(input.parent)
            if c.type == "step" and c.state != State.DONE and c.id != target
        ]
        open_steps.append((input.parent, _NEW_STEP, input.step, graph.phase_for(input.step)))
        mains = main_path_stages(graph)
        for fork in forks(open_steps, lambda item: mains):
            ids = [(sid, stage) for sid, stage in fork.steps if sid != _NEW_STEP]
            if len(ids) == len(fork.steps):
                continue
            names = ", ".join("%s (%s)" % (sid, stage) for sid, stage in ids)
            first = ids[0][0]
            raise UseCaseError(
                "item %s already has an open main-path step in phase %s: %s; remove it "
                "(lc rm %s), close it (lc done %s <outcome>), or pass --replace %s to "
                "remove it and file this step"
                % (input.parent, fork.phase or "(none)", names, first, first, first)
            )

    def _last_closed_step(self, item):
        closed = [
            c
            for c in self._store.children(item)
            if c.state == State.DONE and c.closed_at
        ]
        if not closed:
            return None
        return max(closed, key=lambda c: (c.closed_at, c.created_at or "")).id
