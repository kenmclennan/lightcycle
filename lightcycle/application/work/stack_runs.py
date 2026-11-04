from lightcycle.domain.flow.flow import PROJECT_WORKSPACE
from lightcycle.domain.runs import RunState, has_stack_phase, stack_run_of
from lightcycle.domain.work import State

STACK_RETARGETED = "stack-retargeted"


class StackRuns:
    def __init__(self, store, flow):
        self._store = store
        self._flow = flow

    def run_of(self, parent_id):
        node = self._store.get_node(parent_id)

        def workspace_of(phase):
            return self._flow.workspace_for_phase(node, phase) or PROJECT_WORKSPACE

        return stack_run_of(self._store.runs_of(parent_id), workspace_of)

    def node_runs(self, item_id):
        current = self._store.current_pass(item_id)
        if current is None:
            return []
        node = self._store.get_node(item_id)
        return [
            r for r in self._store.runs_of(item_id, current.id)
            if r.branch and r.state == RunState.OPEN
            and (self._flow.workspace_for_phase(node, r.phase) or PROJECT_WORKSPACE)
            == PROJECT_WORKSPACE
        ]

    def parent_of(self, run, stacks_on):
        if run.slice > 0 and run.base_slice is not None:
            base = [
                r for r in self._store.runs_of(run.item, run.pass_id)
                if r.phase == run.phase and r.slice == run.base_slice
            ]
            return (base[-1] if base else None), "slice"
        if stacks_on:
            return self.run_of(stacks_on), "item"
        return None, None

    def retargeted(self, run):
        return any(
            a.type == STACK_RETARGETED and a.label == run.id
            for a in self._store.item_artifacts(run.item)
        )

    def has_dependents(self, run):
        if any(c.state != State.DONE for c in self._store.items_stacked_on(run.item)):
            stack_run = self.run_of(run.item)
            if stack_run is not None and stack_run.id == run.id:
                return True
        if run.state != RunState.MERGED or not run.branch:
            return False
        return any(
            r.id != run.id and r.state == RunState.OPEN and r.branch
            and r.phase == run.phase and r.base_slice == run.slice
            and not self.retargeted(r)
            for r in self._store.runs_of(run.item, run.pass_id)
        )

    def has_phase(self, parent_id):
        node = self._store.get_node(parent_id)
        graph = self._flow.graph_for(node)
        return graph is not None and has_stack_phase(graph)
