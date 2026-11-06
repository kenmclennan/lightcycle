from dataclasses import dataclass
from typing import Optional, Tuple

from lightcycle.domain.runs.pass_record import pass_number
from lightcycle.domain.work.artifact import Artifact, type_label
from lightcycle.domain.work.outputs import OutputEntry

PR_NAME = "pr"


@dataclass(frozen=True)
class OutputRow:
    key: str
    name: str
    label: Optional[str]
    value: str
    kind: Optional[str]
    step: Optional[str]
    pass_id: Optional[str]
    history: Tuple[OutputEntry, ...] = ()


def _key(name, label):
    return "%s:%s" % (name, label) if label else name


def _run_entry(run):
    return OutputEntry(
        name=PR_NAME, label=run.phase, value=run.pr, kind="url", step=run.phase,
        pass_id=run.pass_id, at=run.opened_at,
    )


def _pr_rows(runs, taken):
    by_phase = {}
    for run in runs:
        if run.pr:
            by_phase.setdefault(run.phase, []).append(run)
    ordered = []
    for phase, phase_runs in by_phase.items():
        newest_first = sorted(phase_runs, key=lambda r: r.opened_at or "", reverse=True)
        ordered.append((newest_first[0].opened_at or "", phase, newest_first))
    ordered.sort(key=lambda c: c[0])
    rows = []
    for _opened, phase, newest_first in ordered:
        current = _run_entry(newest_first[0])
        key = _key(PR_NAME, phase)
        while key in taken:
            key += "+"
        taken.add(key)
        rows.append(OutputRow(
            key=key, name=PR_NAME, label=phase, value=current.value, kind=current.kind,
            step=current.step, pass_id=current.pass_id,
            history=tuple(_run_entry(r) for r in newest_first[1:]),
        ))
    return rows


def output_rows(output_set, runs):
    taken = set()
    rows = []
    for entry in output_set.artifacts:
        key = _key(entry.name, entry.label)
        while key in taken:
            key += "+"
        taken.add(key)
        rows.append(OutputRow(
            key=key, name=entry.name, label=entry.label, value=entry.value, kind=entry.kind,
            step=entry.step, pass_id=entry.pass_id, history=output_set.history_of(entry),
        ))
    return rows + _pr_rows(runs, taken)


@dataclass(frozen=True)
class OutputLine:
    row_key: str
    name: str
    label: Optional[str]
    value: str
    kind: Optional[str]
    step: Optional[str]
    pass_id: Optional[str]
    older: int = 0
    is_history: bool = False

    def as_artifact(self):
        return Artifact(type=self.name, value=self.value, label=self.label, kind=self.kind)

    @property
    def title(self):
        return type_label(self.as_artifact())

    @property
    def pass_text(self):
        return "p%d" % pass_number(self.pass_id) if self.pass_id else ""


def output_lines(rows, expanded):
    lines = []
    for row in rows:
        lines.append(OutputLine(
            row_key=row.key, name=row.name, label=row.label, value=row.value, kind=row.kind,
            step=row.step, pass_id=row.pass_id, older=len(row.history),
        ))
        if row.key not in expanded:
            continue
        for entry in row.history:
            lines.append(OutputLine(
                row_key=row.key, name=entry.name, label=entry.label, value=entry.value,
                kind=entry.kind, step=entry.step, pass_id=entry.pass_id, is_history=True,
            ))
    return lines
