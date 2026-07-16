from dataclasses import dataclass
from typing import List, Optional

from lightcycle.application.work.human_node_row import HumanNodeRow
from lightcycle.application.work.project_of import project_of
from lightcycle.domain.work import Node, State


@dataclass(frozen=True)
class BacklogInput:
    n: Optional[int] = None
    project: Optional[str] = None
    themes: bool = False


@dataclass(frozen=True)
class ThemeGroup:
    theme: Optional[Node]
    project: Optional[str]
    rows: List[HumanNodeRow]


@dataclass(frozen=True)
class BacklogResponse:
    rows: List[HumanNodeRow]
    groups: Optional[List[ThemeGroup]] = None


class BacklogUseCase:
    def __init__(self, store, flow):
        self._store = store
        self._flow = flow

    def execute(self, input: BacklogInput) -> BacklogResponse:
        items = [
            n for n in self._store.all_nodes()
            if n.type == "item" and n.state == State.BACKLOGGED
        ]
        if input.project is not None:
            items = [t for t in items if project_of(self._store, t) == input.project]
        items.sort(key=lambda t: t.id)
        if input.n is not None:
            items = items[:input.n]
        rows = [
            HumanNodeRow(kind="todo", outcomes=[], step=t, project=project_of(self._store, t))
            for t in items
        ]
        if not input.themes:
            return BacklogResponse(rows=rows)
        return BacklogResponse(rows=rows, groups=self._grouped(rows))

    def _grouped(self, rows):
        by_theme, order, no_theme = {}, [], []
        for row in rows:
            theme_id = row.step.theme
            if theme_id is None:
                no_theme.append(row)
                continue
            if theme_id not in by_theme:
                by_theme[theme_id] = []
                order.append(theme_id)
            by_theme[theme_id].append(row)
        groups = []
        for theme_id in sorted(order):
            theme = self._store.get_node(theme_id)
            groups.append(ThemeGroup(theme, project_of(self._store, theme), by_theme[theme_id]))
        if no_theme:
            groups.append(ThemeGroup(None, None, no_theme))
        return groups
