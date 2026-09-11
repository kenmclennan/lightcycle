from dataclasses import dataclass

from lightcycle.application.work.has_feedback import has_feedback
from lightcycle.application.work.project_of import project_of
from lightcycle.domain import feedback as cfeedback
from lightcycle.domain.feedback import parse_reflections, reflections_of


def _durations_of(store, steps):
    result = {}
    for t in steps:
        elapsed = cfeedback.Duration(store.history(t.id)).elapsed()
        result[t.id] = elapsed.total_seconds() if elapsed is not None else None
    return result


def _collect_item_row(store, item, signals_for):
    from lightcycle.application.feedback.retro import ItemSignals

    children = store.children(item.id)
    steps = [c for c in children if c.type == "step"]
    step_pairs = [(s.pass_id, store.item_artifacts(s.id)) for s in steps]
    artifacts = reflections_of(store.item_artifacts(item.id), step_pairs, set())
    refs, unreadable = parse_reflections(artifacts)
    row = ItemSignals(
        item=item, signals=signals_for(item).tally(steps), reflections=len(refs),
        durations=_durations_of(store, steps),
    )
    return row, refs, unreadable


def _collect_pending_item_row(store, item, signals_for):
    from lightcycle.application.feedback.retro import ItemSignals
    from lightcycle.application.work.retroed_passes import retroed_pass_ids

    excluded = retroed_pass_ids(store, item.id)
    children = store.children(item.id)
    steps = [c for c in children if c.type == "step"]
    step_pairs = [(s.pass_id, store.item_artifacts(s.id)) for s in steps]
    artifacts = reflections_of(store.item_artifacts(item.id), step_pairs, excluded)
    refs, unreadable = parse_reflections(artifacts)
    included_steps = [s for s in steps if s.pass_id not in excluded]
    row = ItemSignals(
        item=item, signals=signals_for(item).tally(included_steps), reflections=len(refs),
        durations=_durations_of(store, included_steps),
    )
    return row, refs, unreadable


def _pass_row(store, item, steps, signals_for, refs):
    from lightcycle.application.feedback.retro import ItemSignals

    return ItemSignals(
        item=item, signals=signals_for(item).tally(steps), reflections=len(refs),
        durations=_durations_of(store, steps),
    )


class RetroScope:
    @staticmethod
    def from_input(input) -> "RetroScope":
        if input.subject is not None:
            return SubjectScope(input.subject)
        if input.since is not None:
            return SinceScope(input.since)
        if input.project is not None:
            return ProjectScope(input.project)
        if input.pending:
            return PendingScope()
        return LastNScope(input.last)


@dataclass(frozen=True)
class SubjectScope(RetroScope):
    subject: str

    @property
    def label(self):
        return self.subject

    def items_and_refs(self, store, signals_for):
        subject = store.get_node(self.subject)
        row, refs, unreadable = _collect_item_row(store, subject, signals_for)
        return [row], list(refs), list(unreadable)


@dataclass(frozen=True)
class SinceScope(RetroScope):
    since: str

    @property
    def label(self):
        return "since:%s" % self.since

    def items_and_refs(self, store, signals_for):
        steps = store.nodes_closed_since(self.since)
        item_groups = {}
        orphan_steps = []
        for step in steps:
            if step.item:
                item_groups.setdefault(step.item, []).append(step)
            else:
                orphan_steps.append(step)
        all_refs = []
        all_unreadable = []
        rows = []
        for item_id, item_steps in item_groups.items():
            refs, unreadable = [], []
            for t in item_steps:
                r, u = parse_reflections(store.item_artifacts(t.id))
                refs.extend(r)
                unreadable.extend(u)
            all_refs.extend(refs)
            all_unreadable.extend(unreadable)
            item = store.get_node(item_id)
            rows.append(_pass_row(store, item, item_steps, signals_for, refs))
        for step in orphan_steps:
            r, u = parse_reflections(store.item_artifacts(step.id))
            all_refs.extend(r)
            all_unreadable.extend(u)
        return rows, all_refs, all_unreadable


@dataclass(frozen=True)
class ProjectScope(RetroScope):
    project: str

    @property
    def label(self):
        return "project:%s" % self.project

    def items_and_refs(self, store, signals_for):
        rows, all_refs, all_unreadable = [], [], []
        for item in store.closed_unretroed_items():
            if project_of(store, item) != self.project:
                continue
            row, refs, unreadable = _collect_item_row(store, item, signals_for)
            rows.append(row)
            all_refs.extend(refs)
            all_unreadable.extend(unreadable)
        return rows, all_refs, all_unreadable


@dataclass(frozen=True)
class PendingScope(RetroScope):
    @property
    def label(self):
        return "pending"

    def items_and_refs(self, store, signals_for):
        rows, all_refs, all_unreadable = [], [], []
        for item in store.closed_unretroed_items():
            if not has_feedback(store, item):
                continue
            row, refs, unreadable = _collect_pending_item_row(store, item, signals_for)
            if not refs and not unreadable:
                continue
            rows.append(row)
            all_refs.extend(refs)
            all_unreadable.extend(unreadable)
        for pass_record in store.closed_unretroed_passes():
            steps = [s for s in store.children(pass_record.item) if s.pass_id == pass_record.id]
            refs, unreadable = [], []
            for t in steps:
                r, u = parse_reflections(store.item_artifacts(t.id))
                refs.extend(r)
                unreadable.extend(u)
            if not refs and not unreadable:
                continue
            item = store.get_node(pass_record.item)
            rows.append(_pass_row(store, item, steps, signals_for, refs))
            all_refs.extend(refs)
            all_unreadable.extend(unreadable)
        return rows, all_refs, all_unreadable


@dataclass(frozen=True)
class LastNScope(RetroScope):
    last: int

    @property
    def label(self):
        return "last:%d" % self.last

    def items_and_refs(self, store, signals_for):
        rows, all_refs, all_unreadable = [], [], []
        for item in store.last_n_closed_items(self.last):
            row, refs, unreadable = _collect_item_row(store, item, signals_for)
            rows.append(row)
            all_refs.extend(refs)
            all_unreadable.extend(unreadable)
        return rows, all_refs, all_unreadable
