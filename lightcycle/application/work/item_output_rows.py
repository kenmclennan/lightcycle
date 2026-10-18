from lightcycle.application.work.item_outputs import ItemOutputs
from lightcycle.domain.work.output_rows import output_rows


class ItemOutputRows:
    def __init__(self, store, flow):
        self._store = store
        self._outputs = ItemOutputs(store, flow)

    def for_item(self, item):
        return output_rows(self._outputs.for_item(item.id), self._store.runs_of(item.id))
