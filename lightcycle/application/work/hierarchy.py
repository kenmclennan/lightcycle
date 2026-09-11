from dataclasses import dataclass
from typing import List

from lightcycle.domain.runs import pass_number
from lightcycle.domain.work import HierarchyRow, compose_hierarchy


@dataclass(frozen=True)
class HierarchyInput:
    node: str


@dataclass(frozen=True)
class HierarchyResponse:
    rows: List[HierarchyRow]
    multi_pass: bool


class HierarchyUseCase:
    def __init__(self, store):
        self._store = store

    def execute(self, input: HierarchyInput) -> HierarchyResponse:
        node = self._store.get_node(input.node)
        root = self._resolve_root(node)
        steps = self._store.children(root.id)
        steps_by_item = {root.id: steps}
        current = self._store.current_pass(root.id)
        multi_pass = (current is not None and current.n > 1) or any(
            pass_number(step.pass_id) > 1 for step in steps
        )
        return HierarchyResponse(rows=compose_hierarchy(root, steps_by_item), multi_pass=multi_pass)

    def _resolve_root(self, node):
        return node if node.type == "item" else self._store.get_node(node.item)
