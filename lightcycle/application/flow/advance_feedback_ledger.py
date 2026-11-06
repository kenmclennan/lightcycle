from lightcycle.domain.work import State


class AdvanceFeedbackLedgerUseCase:
    def __init__(self, store, flow, clock):
        self._store = store
        self._flow = flow
        self._clock = clock

    def execute(self, step_id):
        step = self._store.get_node(step_id)
        step_def = self._flow.flow_for(step).step_def(step.stage)
        if step_def.pr_feedback is None:
            return
        if any(
            node.watched_step == step_id and node.state != State.DONE
            for node in self._store.children(step.item)
        ):
            return
        run = self._store.current_run(step.item, step_def.phase)
        if run is None:
            return
        closed_at = self._clock()
        if _epoch(run.comments_dispatched_through) >= closed_at:
            return
        self._store.set_comments_dispatched_through(run.id, str(closed_at))


def _epoch(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
