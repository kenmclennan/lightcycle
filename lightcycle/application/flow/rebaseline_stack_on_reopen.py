from lightcycle.application.pool.stack_reads import rebaseline


class RebaselineStackOnReopenUseCase:
    def __init__(self, store, github, flow):
        self._store = store
        self._github = github
        self._flow = flow

    def execute(self, step_id, outcome):
        step = self._store.get_node(step_id)
        if step is None or not step.item:
            return
        flow = self._flow.flow_for(step)
        if step.stage not in flow.stack_review_stages():
            return
        destination = flow.step_def(step.stage).routes.get(outcome)
        if destination is None or not flow.step_def(destination).pr_stack_shape:
            return
        run = self._store.current_run(step.item, flow.step_def(step.stage).phase)
        if run is None or not run.stack:
            return
        rebaseline(self._store, self._github, run)
