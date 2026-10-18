from dataclasses import dataclass
from typing import Optional, Tuple

from lightcycle.application.work.item_outputs import ItemOutputs
from lightcycle.application.work.step_inputs import StepInputs
from lightcycle.ports.store import NodeNotFoundError

SECTION_INPUTS = "inputs"
SECTION_OUTPUTS = "outputs"
SECTION_RECORDS = "records"
SOURCE_ITEM = "item"
NOT_RECORDED = "not recorded"
GUIDANCE_RECORD_TYPES = ("guidance-delivered", "guidance-skipped", "guidance-cited")


@dataclass(frozen=True)
class ContextRow:
    section: str
    key: str
    source: str = ""
    pass_id: str = ""
    value: Optional[str] = None
    kind: str = "text"


@dataclass(frozen=True)
class StepContextView:
    rows: Tuple[ContextRow, ...]
    inputs_live: bool = False


def _entry_key(entry):
    label = entry.get("label")
    return "%s:%s" % (entry["name"], label) if label else entry["name"]


def _record_value(row):
    if row.type in GUIDANCE_RECORD_TYPES:
        return ", ".join(line.strip() for line in (row.value or "").splitlines() if line.strip())
    return row.value


class StepContext:
    def __init__(self, store, flow):
        self._store = store
        self._inputs = StepInputs(store, flow)
        self._outputs = ItemOutputs(store, flow)

    def read(self, step) -> StepContextView:
        body = self._inputs.read(step)
        rows = list(self._input_rows(body))
        rows.extend(self._output_rows(step))
        rows.extend(self._record_rows(step))
        return StepContextView(rows=tuple(rows), inputs_live=bool(body) and body.get("frozen") is False)

    def _input_rows(self, body):
        if body is None:
            return [ContextRow(SECTION_INPUTS, NOT_RECORDED)]
        rows = []
        context = body.get("context") or {}
        for name in ("description", "repo", "workflow"):
            if context.get(name):
                rows.append(ContextRow(SECTION_INPUTS, name, SOURCE_ITEM, "", context[name]))
        for entry in body.get("item") or []:
            rows.append(ContextRow(
                SECTION_INPUTS, _entry_key(entry), entry.get("step") or SOURCE_ITEM,
                entry.get("pass") or "", entry["value"], entry.get("kind") or "text",
            ))
        previous = body.get("previous")
        if previous:
            if previous.get("report"):
                rows.append(ContextRow(
                    SECTION_INPUTS, "report", previous["step"], self._pass_of(previous["step"]),
                    previous["report"],
                ))
            for entry in previous.get("outputs") or []:
                rows.append(ContextRow(
                    SECTION_INPUTS, _entry_key(entry), previous["step"], entry.get("pass") or "",
                    entry["value"], entry.get("kind") or "text",
                ))
        return rows

    def _pass_of(self, step_id):
        try:
            return self._store.get_node(step_id).pass_id or ""
        except NodeNotFoundError:
            return ""

    def _output_rows(self, step):
        rows = []
        if step.report:
            rows.append(ContextRow(SECTION_OUTPUTS, "report", value=step.report))
        for entry in self._inputs.entry_dicts_for_step(step):
            rows.append(ContextRow(
                SECTION_OUTPUTS, _entry_key(entry), value=entry["value"],
                kind=entry.get("kind") or "text",
            ))
        return rows

    def _record_rows(self, step):
        _outputs, records = self._outputs.step_rows(step)
        return [
            ContextRow(
                SECTION_RECORDS, "%s:%s" % (r.type, r.label) if r.label else r.type,
                value=_record_value(r), kind=r.kind or "text",
            )
            for r in records
        ]
