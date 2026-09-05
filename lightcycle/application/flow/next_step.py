from lightcycle.domain.work.state import State


def _tie_break(step_id):
    tail = step_id.rsplit(".", 1)[-1]
    return int(tail) if tail.isdigit() else 0


class NextStepResolver:
    def __init__(self, store, flow):
        self._store = store
        self._flow = flow

    def resolve(self, t, outcome, name):
        transition = self._flow.flow_next(t.step, outcome, name)
        if transition is None:
            return None
        cap_outcome = self._flow.ci_failed_cap_outcome(t.step, name)
        prior = 0
        if cap_outcome is not None and outcome == cap_outcome:
            history = sorted(
                (
                    s for s in self._store.steps_at_step(t.step)
                    if s.parent == t.parent and s.state == State.DONE
                ),
                key=lambda s: (s.created_at or "", _tie_break(s.id)),
            )
            for s in history:
                prior = prior + 1 if s.outcome == outcome else 0
        return self._flow.effective_transition(transition, outcome, prior, name)

    def create(self, t, transition):
        spec = transition.next_step_spec(t, self._store.get_node(t.parent).title)
        return self._store.create_step(**spec.as_kwargs())
