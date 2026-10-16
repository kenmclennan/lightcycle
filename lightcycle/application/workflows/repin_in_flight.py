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
    def __init__(self, store, source, flow, pin_drift, config):
        self._store = store
        self._source = source
        self._flow = flow
        self._pin_drift = pin_drift
        self._config = config

    def _open_steps(self, item_id):
        return [
            (s.stage or s.role, s.state == State.RUNNING)
            for s in self._store.children(item_id)
            if s.type == "step" and s.state != State.DONE
        ]

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
            if not ahead:
                continue
            if not self._pin_drift.new_graph_declares(origin, name, current, open_steps):
                held.append(HeldItem(
                    item.id, "open step is not in the new graph of %s/%s" % (origin, name)))
                continue
            try:
                resolved = resolver.execute(ResolveWorkflowSelectionInput(
                    node_id=item.id, node_type=item.type, selector="%s/%s" % (origin, name)))
                editor.execute(EditNodeInput(step=item.id, workflow=resolved.value))
            except UseCaseError as e:
                held.append(HeldItem(item.id, str(e)))
                continue
            repinned.append(RepinnedItem(item.id, item.title, resolved.value, ahead))
        return RepinResponse(repinned=repinned, held=held, left=in_flight - len(repinned))
