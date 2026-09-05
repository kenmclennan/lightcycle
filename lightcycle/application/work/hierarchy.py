from dataclasses import dataclass
from typing import List

from lightcycle.domain.work import HierarchyRow, compose_hierarchy


@dataclass(frozen=True)
class HierarchyInput:
    node: str


@dataclass(frozen=True)
class HierarchyResponse:
    rows: List[HierarchyRow]


class HierarchyUseCase:
    def __init__(self, store):
        self._store = store

    def execute(self, input: HierarchyInput) -> HierarchyResponse:
        node = self._store.get_node(input.node)
        root = self._resolve_root(node)
        steps_by_item = {root.id: self._store.children(root.id)}
        passes_by_item = {root.id: self._store.passes_of(root.id)}
        return HierarchyResponse(rows=compose_hierarchy(root, steps_by_item, passes_by_item))

    def _resolve_root(self, node):
        return node if node.type == "item" else self._store.get_node(node.parent)
