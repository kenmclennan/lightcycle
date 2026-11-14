from lightcycle.application.flow.cap_restart import (
    stage_escalation_firing_ids,
    step_order_key,
)
from lightcycle.domain.flow.flow import since_last_firing
from lightcycle.domain.work.state import State


class NextStepResolver:
    def __init__(self, store, flow):
        self._store = store
        self._flow = flow

    def _history(self, t, name=None):
        history = sorted(
            (
                s for s in self._store.steps_at_step(t.stage)
                if s.item == t.item and s.state == State.DONE
            ),
            key=step_order_key,
        )
        flow = self._flow.load_flow(name)
        firing = stage_escalation_firing_ids(self._store, flow, t.item, t.stage, history)
        return since_last_firing(history, firing)

    def resolve(self, t, outcome, name):
        transition = self._flow.flow_next(t.stage, outcome, name)
        if transition is None:
            return None
        return self._flow.escalated_transition(transition, outcome, lambda: self._history(t, name), name)

    def spec_for(self, t, transition):
        if transition is None:
            return None
        return transition.next_step_spec(t)

    def create(self, t, transition):
        spec = self.spec_for(t, transition)
        return self._store.create_step(**spec.as_kwargs())
