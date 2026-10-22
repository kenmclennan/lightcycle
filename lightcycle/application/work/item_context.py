from dataclasses import dataclass
from typing import Optional, Tuple

from lightcycle.domain.work import State


@dataclass(frozen=True)
class ItemContext:
    repo: Optional[str] = None
    workflow: Optional[str] = None
    resolves: Tuple[Tuple[str, Optional[str]], ...] = ()
    note: Optional[str] = None


class ItemContextReader:
    def __init__(self, store):
        self._store = store

    def read(self, item):
        return ItemContext(
            repo=item.repo or None,
            workflow=item.workflow or None,
            resolves=self._resolves(item.id),
            note=item.note if item.state == State.DONE and item.note else None,
        )

    def _resolves(self, item_id):
        return tuple(
            (a.value, self._title(a.value))
            for a in self._store.item_artifacts(item_id) if a.type == "resolves"
        )

    def _title(self, ref_id):
        try:
            return self._store.get_node(ref_id).title or None
        except KeyError:
            return None
