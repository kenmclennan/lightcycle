from lightcycle.domain.flow.flow import PROJECT_WORKSPACE
from lightcycle.domain.runs import has_stack_phase, stack_run_of


class StackRuns:
    def __init__(self, store, flow):
        self._store = store
        self._flow = flow

    def run_of(self, parent_id):
        node = self._store.get_node(parent_id)

        def workspace_of(phase):
            return self._flow.workspace_for_phase(node, phase) or PROJECT_WORKSPACE

        return stack_run_of(self._store.runs_of(parent_id), workspace_of)

    def has_phase(self, parent_id):
        node = self._store.get_node(parent_id)
        graph = self._flow.graph_for(node)
        return graph is not None and has_stack_phase(graph)
