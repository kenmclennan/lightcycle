import json
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from lightcycle.domain import feedback as cfeedback
from lightcycle.domain.work import Item, Node


@dataclass(frozen=True)
class RetroInput:
    subject: Optional[str] = None
    since: Optional[str] = None
    last: Optional[int] = None
    project: Optional[str] = None


@dataclass(frozen=True)
class FeedbackItem:
    step: str
    text: str


@dataclass(frozen=True)
class ItemSignals:
    item: Node
    signals: Dict[str, Dict[str, int]]
    reflections: int
    durations: Dict[str, Optional[float]] = field(default_factory=dict)

    def total_duration(self) -> Optional[float]:
        known = [v for v in self.durations.values() if v is not None]
        return sum(known) if known else None


@dataclass(frozen=True)
class RetroResponse:
    subject: str
    reflection_count: int
    feedback: List[FeedbackItem]
    item_signals: List[ItemSignals]


class RetroUseCase:
    def __init__(self, store, flow, config=None):
        self._store = store
        self._flow = flow
        self._config = config

    def _project_of(self, item, default):
        return Item(item.id, tuple(self._store.item_artifacts(item.id))).repo(default)

    def _project_scope(self, project, signals):
        default = os.path.basename(self._config.engine_root())
        rows, all_refs = [], []
        for item in self._store.closed_unretroed_items():
            if self._project_of(item, default) != project:
                continue
            row, refs = self._collect_item_row(item, signals)
            rows.append(row)
            all_refs.extend(refs)
        return rows, all_refs

    def _reflections_of(self, node_id):
        out = []
        for art in self._store.item_artifacts(node_id):
            if art.type == "reflection":
                try:
                    out.append(cfeedback.Reflection.from_dict(json.loads(art.value)))
                except (ValueError, KeyError):
                    pass
        return out

    def _durations_of(self, steps):
        result = {}
        for t in steps:
            elapsed = cfeedback.Duration(self._store.history(t.id)).elapsed()
            result[t.id] = elapsed.total_seconds() if elapsed is not None else None
        return result

    def _collect_item_row(self, item, signals):
        children = self._store.children(item.id)
        steps = [c for c in children if c.type == "step"]
        refs = []
        for t in steps:
            refs.extend(self._reflections_of(t.id))
        row = ItemSignals(
            item=item, signals=signals.tally(steps), reflections=len(refs),
            durations=self._durations_of(steps),
        )
        return row, refs

    def _theme_scope(self, subject_id, signals):
        children = self._store.children(subject_id)
        items = [c for c in children if c.type == "item"]
        all_refs = []
        rows = []
        for item in items:
            row, refs = self._collect_item_row(item, signals)
            rows.append(row)
            all_refs.extend(refs)
        for child in children:
            if child.type != "item":
                all_refs.extend(self._reflections_of(child.id))
        return rows, all_refs

    def execute(self, input: RetroInput) -> RetroResponse:
        signals = cfeedback.Signals.from_graph(self._flow.load_graph())

        if input.subject is not None:
            children = self._store.children(input.subject)
            if any(c.type == "item" for c in children):
                rows, all_refs = self._theme_scope(input.subject, signals)
            else:
                subject = self._store.get_node(input.subject)
                row, refs = self._collect_item_row(subject, signals)
                rows = [row]
                all_refs = list(refs)
            label = input.subject

        elif input.since is not None:
            steps = self._store.nodes_closed_since(input.since)
            item_groups = {}
            orphan_steps = []
            for step in steps:
                if step.parent:
                    item_groups.setdefault(step.parent, []).append(step)
                else:
                    orphan_steps.append(step)
            all_refs = []
            rows = []
            for item_id, item_steps in item_groups.items():
                refs = []
                for t in item_steps:
                    refs.extend(self._reflections_of(t.id))
                all_refs.extend(refs)
                item = self._store.get_node(item_id)
                rows.append(
                    ItemSignals(
                        item=item, signals=signals.tally(item_steps), reflections=len(refs),
                        durations=self._durations_of(item_steps),
                    )
                )
            for step in orphan_steps:
                all_refs.extend(self._reflections_of(step.id))
            label = "since:%s" % input.since

        elif input.project is not None:
            rows, all_refs = self._project_scope(input.project, signals)
            label = "project:%s" % input.project

        else:
            themes = self._store.last_n_closed_themes(input.last)
            all_refs = []
            rows = []
            for theme in themes:
                epic_rows, epic_refs = self._theme_scope(theme.id, signals)
                rows.extend(epic_rows)
                all_refs.extend(epic_refs)
            label = "last:%d" % input.last

        feedback = [
            FeedbackItem(step=f["step"], text=f["feedback"])
            for f in cfeedback.Retro(all_refs).feedback()
        ]
        return RetroResponse(
            subject=label, reflection_count=len(all_refs), feedback=feedback, item_signals=rows
        )
