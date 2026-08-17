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
        if root.type == "theme":
            items = self._store.children(root.id)
            steps_by_item = {item.id: self._store.children(item.id) for item in items}
        else:
            items = []
            steps_by_item = {root.id: self._store.children(root.id)}
        return HierarchyResponse(rows=compose_hierarchy(root, items, steps_by_item))

    def _resolve_root(self, node):
        if node.type == "theme":
            return node
        item = node if node.type == "item" else self._store.get_node(node.parent)
        if item.parent:
            return self._store.get_node(item.parent)
        return item
