from lightcycle.domain.work.state import State


class NextStepResolver:
    def __init__(self, store, flow):
        self._store = store
        self._flow = flow

    def resolve(self, t, outcome, name, project):
        transition = self._flow.flow_next(t.step, outcome, name, project)
        if transition is None:
            return None
        cap_outcome = self._flow.ci_failed_cap_outcome(t.step, name, project)
        prior = 0
        if cap_outcome is not None and outcome == cap_outcome:
            prior = sum(
                1 for s in self._store.steps_at_step(t.step)
                if s.parent == t.parent and s.state == State.DONE and s.outcome == outcome
            )
        return self._flow.effective_transition(transition, outcome, prior, name, project)

    def create(self, t, transition):
        return self._store.create_step(**transition.next_step_spec(t).as_kwargs())
