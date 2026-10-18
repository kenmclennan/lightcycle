import datetime
import json

from lightcycle.application.work.item_outputs import ItemOutputs
from lightcycle.ports.store import NodeNotFoundError
from lightcycle.domain.work.outputs import OutputEntry, OutputSet


def _entry_dicts_for_step(step, rows):
    at = step.closed_at or step.created_at
    return [
        OutputEntry(
            name=r.type, label=r.label, value=r.value, kind=r.kind, step=step.id,
            pass_id=step.pass_id, at=at,
        ).as_dict()
        for r in rows
    ]


class StepInputs:
    def __init__(self, store, flow, now=None):
        self._store = store
        self._flow = flow
        self._outputs = ItemOutputs(store, flow)
        self._now = now or (lambda: datetime.datetime.now().astimezone().isoformat())

    def build(self, step) -> dict:
        item = self._store.get_item(step.item)
        outputs: OutputSet = self._outputs.for_reader(step)
        previous = None
        prev = self._previous(step)
        if prev is not None:
            produced, _records = self._outputs.step_rows(prev)
            previous = {
                "step": prev.id,
                "stage": prev.stage,
                "outcome": prev.outcome,
                "report": prev.report,
                "outputs": _entry_dicts_for_step(prev, produced),
            }
        return {
            "context": {
                "description": item.description, "repo": item.repo, "workflow": item.workflow,
            },
            "item": outputs.entry_dicts(),
            "previous": previous,
        }

    def _previous(self, step):
        if not step.previous_step:
            return None
        try:
            return self._store.get_node(step.previous_step)
        except NodeNotFoundError:
            return None

    def previous(self, step):
        return self._previous(step)

    def freeze(self, step):
        self._store.save_step_inputs(step.id, self._now(), json.dumps(self.build(step)))

    def read(self, step):
        row = self._store.step_inputs(step.id)
        if row is not None:
            frozen_at, body = row
            return dict(json.loads(body), frozen=True, frozen_at=frozen_at)
        return dict(self.build(step), frozen=False, frozen_at=None)

    def entry_dicts_for_step(self, step):
        produced, _records = self._outputs.step_rows(step)
        return _entry_dicts_for_step(step, produced)
