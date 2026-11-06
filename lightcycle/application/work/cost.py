from dataclasses import dataclass, replace

from lightcycle.domain.feedback import layers
from lightcycle.domain.work.cost import item_cost, step_cost


@dataclass(frozen=True)
class CostInput:
    node: str


class CostUseCase:
    def __init__(self, store):
        self._store = store

    def execute(self, input: CostInput):
        node = self._store.get_node(input.node)
        if node.type == "item":
            runs = self._store.runs_of(node.id)
            return replace(
                item_cost(self._store.children(node.id)),
                prs=layers.prs_of(runs), prs_merged=layers.prs_merged_of(runs),
            )
        return step_cost(node, self._store.tool_usage_for(node.id))
