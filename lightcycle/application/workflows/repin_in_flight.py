import time
from dataclasses import dataclass, field
from typing import List

from lightcycle.application.errors import UseCaseError
from lightcycle.application.work.edit_node import EditNodeInput, EditNodeUseCase
from lightcycle.application.work.resolve_workflow_selection import (
    ResolveWorkflowSelectionInput,
    ResolveWorkflowSelectionUseCase,
)
from lightcycle.domain.work.state import State
from lightcycle.domain.workflows.identity import parse_pin


@dataclass(frozen=True)
class RepinnedItem:
    id: str
    title: str
    pin: str
    changed_steps: List[str]


@dataclass(frozen=True)
class HeldItem:
    id: str
    reason: str


@dataclass(frozen=True)
class RepinResponse:
    repinned: List[RepinnedItem] = field(default_factory=list)
    held: List[HeldItem] = field(default_factory=list)
    left: int = 0


class RepinInFlightItemsUseCase:
    def __init__(self, store, source, flow, pin_drift, config, worker_log):
        self._store = store
        self._source = source
        self._flow = flow
        self._pin_drift = pin_drift
        self._config = config
        self._worker_log = worker_log

    def _open_steps(self, item_id):
        return [
            (s.stage or s.role, s.state == State.RUNNING)
            for s in self._store.children(item_id)
            if s.type == "step" and s.state != State.DONE
        ]

    def _owner_changes(self, item_id, flow):
        changes = []
        for s in self._store.children(item_id):
            if s.type != "step" or s.state in (State.DONE, State.RUNNING):
                continue
            owner = flow.step_def(s.stage).owner if s.stage else None
            if owner is not None and owner != s.role:
                changes.append((s, owner))
        return changes

    def _reown(self, step, owner):
        if step.park:
            if step.role:
                self._store.label_remove(step.id, "for:%s" % step.role)
            self._store.label_add(step.id, "for:%s" % owner)
        else:
            self._store.reassign(step.id, owner)
        return "%s  %-7s  %s\n" % (
            time.strftime("%H:%M:%S", time.localtime()), "repin",
            "%s step %s (%s) owner %s -> %s" % (step.item, step.id, step.stage, step.role, owner))

    def execute(self, origin) -> RepinResponse:
        current = self._source.current_sha(origin)
        resolver = ResolveWorkflowSelectionUseCase(self._flow, self._store)
        editor = EditNodeUseCase(self._store, self._config)
        repinned, held, in_flight = [], [], 0
        for item in self._store.all_items_including_done():
            if item.state == State.DONE:
                continue
            parsed = parse_pin(item.workflow)
            if not parsed or parsed[0] != origin or parsed[2] == current:
                continue
            in_flight += 1
            _origin, name, sha = parsed
            open_steps = self._open_steps(item.id)
            try:
                ahead = self._pin_drift.changed_steps_ahead(open_steps, origin, name, sha, current)
            except ValueError as e:
                held.append(HeldItem(item.id, "cannot compare pins: %s" % e))
                continue
            new_flow = self._pin_drift.new_flow(origin, name, current)
            if new_flow is None:
                held.append(HeldItem(
                    item.id, "cannot load the new graph of %s/%s" % (origin, name)))
                continue
            missing = sorted({stage for stage, _running in open_steps if not new_flow.declared(stage)})
            if missing:
                held.append(HeldItem(
                    item.id, "open step %s is not in the new graph of %s/%s" % (
                        ", ".join(repr(m) for m in missing), origin, name)))
                continue
            owner_changes = self._owner_changes(item.id, new_flow)
            if not ahead and not owner_changes:
                continue
            try:
                with self._store.transaction():
                    resolved = resolver.execute(ResolveWorkflowSelectionInput(
                        node_id=item.id, node_type=item.type, selector="%s/%s" % (origin, name)))
                    editor.execute(EditNodeInput(step=item.id, workflow=resolved.value))
                    log_lines = [self._reown(step, owner) for step, owner in owner_changes]
            except UseCaseError as e:
                held.append(HeldItem(item.id, str(e)))
                continue
            for line in log_lines:
                self._worker_log.append_run_log(line)
            repinned.append(RepinnedItem(
                item.id, item.title, resolved.value,
                sorted(set(ahead) | {step.stage for step, _owner in owner_changes})))
        return RepinResponse(repinned=repinned, held=held, left=in_flight - len(repinned))
