from lightcycle.domain.contracts import StepContract
from lightcycle.domain.runs.pass_record import pass_number
from lightcycle.domain.work.outputs import StepFacts, classify_step_rows, resolve_outputs


class ItemOutputs:
    def __init__(self, store, flow):
        self._store = store
        self._flow = flow
        self._declared_cache = {}

    def declared_types(self, step):
        return self._declared(self._flow.workflow_for(step), step.stage)

    def _declared(self, workflow, stage):
        key = (workflow, stage)
        if key not in self._declared_cache:
            try:
                meta = self._flow.meta_for_step(stage, workflow)
            except (ValueError, KeyError):
                meta = {}
            self._declared_cache[key] = frozenset(StepContract.from_meta(meta).produced_types())
        return self._declared_cache[key]

    def _item_id(self, node):
        return getattr(node, "item", None) or node.id

    def _facts(self, item_id):
        steps = [s for s in self._store.children(item_id) if s.type == "step"]
        if not steps:
            return {}
        workflow = self._flow.workflow_for(steps[0])
        return {
            s.id: StepFacts(
                id=s.id, pass_id=s.pass_id, declared=self._declared(workflow, s.stage),
                at=s.closed_at or s.created_at,
            )
            for s in steps
        }

    def _reader_pass(self, node):
        if getattr(node, "type", None) == "step" and node.pass_id:
            return pass_number(node.pass_id)
        return None

    def for_reader(self, node):
        item_id = self._item_id(node)
        return resolve_outputs(
            item_id, self._store.artifact_log(item_id), self._facts(item_id),
            self._reader_pass(node),
        )

    def for_item(self, item_id):
        return resolve_outputs(
            item_id, self._store.artifact_log(item_id), self._facts(item_id), None)

    def present_types(self, node):
        return set(self._store.present_types(node)) | self.for_reader(node).types

    def step_rows(self, step):
        return classify_step_rows(
            self._store.item_artifacts(step.id), self.declared_types(step))

    def reader_artifacts(self, node, outputs=None):
        outputs = outputs if outputs is not None else self.for_reader(node)
        item_rows = list(self._store.item_artifacts(self._item_id(node)))
        shadowed = {(e.name, e.label) for e in outputs.artifacts if e.step is None}
        promoted = [
            e.as_artifact() for e in outputs.artifacts
            if e.step is not None and (e.name, e.label) not in shadowed
        ]
        return item_rows + promoted
