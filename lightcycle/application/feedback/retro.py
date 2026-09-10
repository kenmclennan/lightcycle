from dataclasses import dataclass, field
from typing import Dict, List, Optional

from lightcycle.application.work.has_feedback import has_feedback
from lightcycle.application.work.project_of import project_of
from lightcycle.application.work.retroed_passes import retroed_pass_ids
from lightcycle.domain import feedback as cfeedback
from lightcycle.domain.feedback import parse_reflections, reflections_of
from lightcycle.domain.work import Item


@dataclass(frozen=True)
class RetroInput:
    subject: Optional[str] = None
    since: Optional[str] = None
    last: Optional[int] = None
    project: Optional[str] = None
    pending: bool = False


@dataclass(frozen=True)
class FeedbackItem:
    step: str
    text: str


@dataclass(frozen=True)
class ItemSignals:
    item: Item
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
    unreadable: List[str] = field(default_factory=list)


class RetroUseCase:
    def __init__(self, store, flow):
        self._store = store
        self._flow = flow

    def _signals_resolver(self):
        cache = {}
        empty = cfeedback.Signals([])

        def resolve(item):
            selection = self._flow.inherited_selection(item)
            if selection is None:
                return empty
            if selection not in cache:
                try:
                    pin = self._flow.resolve_selection(selection)
                    cache[selection] = cfeedback.Signals.from_graph(self._flow.load_graph(pin))
                except ValueError:
                    cache[selection] = empty
            return cache[selection]

        return resolve

    def _project_scope(self, project, signals_for):
        rows, all_refs, all_unreadable = [], [], []
        for item in self._store.closed_unretroed_items():
            if project_of(self._store, item) != project:
                continue
            row, refs, unreadable = self._collect_item_row(item, signals_for)
            rows.append(row)
            all_refs.extend(refs)
            all_unreadable.extend(unreadable)
        return rows, all_refs, all_unreadable

    def _pending_scope(self, signals_for):
        rows, all_refs, all_unreadable = [], [], []
        for item in self._store.closed_unretroed_items():
            if not has_feedback(self._store, item):
                continue
            row, refs, unreadable = self._collect_pending_item_row(item, signals_for)
            if not refs and not unreadable:
                continue
            rows.append(row)
            all_refs.extend(refs)
            all_unreadable.extend(unreadable)
        for pass_record in self._store.closed_unretroed_passes():
            steps = [
                s for s in self._store.children(pass_record.item) if s.pass_id == pass_record.id
            ]
            refs, unreadable = [], []
            for t in steps:
                r, u = parse_reflections(self._store.item_artifacts(t.id))
                refs.extend(r)
                unreadable.extend(u)
            if not refs and not unreadable:
                continue
            item = self._store.get_node(pass_record.item)
            rows.append(ItemSignals(
                item=item, signals=signals_for(item).tally(steps), reflections=len(refs),
                durations=self._durations_of(steps),
            ))
            all_refs.extend(refs)
            all_unreadable.extend(unreadable)
        return rows, all_refs, all_unreadable

    def _collect_pending_item_row(self, item, signals_for):
        excluded = retroed_pass_ids(self._store, item.id)
        children = self._store.children(item.id)
        steps = [c for c in children if c.type == "step"]
        step_pairs = [(s.pass_id, self._store.item_artifacts(s.id)) for s in steps]
        artifacts = reflections_of(self._store.item_artifacts(item.id), step_pairs, excluded)
        refs, unreadable = parse_reflections(artifacts)
        included_steps = [s for s in steps if s.pass_id not in excluded]
        row = ItemSignals(
            item=item, signals=signals_for(item).tally(included_steps), reflections=len(refs),
            durations=self._durations_of(included_steps),
        )
        return row, refs, unreadable

    def _durations_of(self, steps):
        result = {}
        for t in steps:
            elapsed = cfeedback.Duration(self._store.history(t.id)).elapsed()
            result[t.id] = elapsed.total_seconds() if elapsed is not None else None
        return result

    def _collect_item_row(self, item, signals_for):
        children = self._store.children(item.id)
        steps = [c for c in children if c.type == "step"]
        step_pairs = [(s.pass_id, self._store.item_artifacts(s.id)) for s in steps]
        artifacts = reflections_of(self._store.item_artifacts(item.id), step_pairs, set())
        refs, unreadable = parse_reflections(artifacts)
        row = ItemSignals(
            item=item, signals=signals_for(item).tally(steps), reflections=len(refs),
            durations=self._durations_of(steps),
        )
        return row, refs, unreadable

    def execute(self, input: RetroInput) -> RetroResponse:
        signals_for = self._signals_resolver()

        if input.subject is not None:
            subject = self._store.get_node(input.subject)
            row, refs, unreadable = self._collect_item_row(subject, signals_for)
            rows = [row]
            all_refs = list(refs)
            all_unreadable = list(unreadable)
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
            all_unreadable = []
            rows = []
            for item_id, item_steps in item_groups.items():
                refs, unreadable = [], []
                for t in item_steps:
                    r, u = parse_reflections(self._store.item_artifacts(t.id))
                    refs.extend(r)
                    unreadable.extend(u)
                all_refs.extend(refs)
                all_unreadable.extend(unreadable)
                item = self._store.get_node(item_id)
                rows.append(
                    ItemSignals(
                        item=item, signals=signals_for(item).tally(item_steps), reflections=len(refs),
                        durations=self._durations_of(item_steps),
                    )
                )
            for step in orphan_steps:
                r, u = parse_reflections(self._store.item_artifacts(step.id))
                all_refs.extend(r)
                all_unreadable.extend(u)
            label = "since:%s" % input.since

        elif input.project is not None:
            rows, all_refs, all_unreadable = self._project_scope(input.project, signals_for)
            label = "project:%s" % input.project

        elif input.pending:
            rows, all_refs, all_unreadable = self._pending_scope(signals_for)
            label = "pending"

        else:
            all_refs = []
            all_unreadable = []
            rows = []
            for item in self._store.last_n_closed_items(input.last):
                row, refs, unreadable = self._collect_item_row(item, signals_for)
                rows.append(row)
                all_refs.extend(refs)
                all_unreadable.extend(unreadable)
            label = "last:%d" % input.last

        reflection_count = len(all_refs)
        feedback = [
            FeedbackItem(step=f["step"], text=f["feedback"])
            for f in cfeedback.Retro(all_refs).feedback()
        ]
        return RetroResponse(
            subject=label, reflection_count=reflection_count, feedback=feedback, item_signals=rows,
            unreadable=all_unreadable,
        )
