import datetime

from lightcycle.domain.flow import consecutive_outcome_count
from lightcycle.domain.work.node_id import node_id_key
from lightcycle.domain.work.state import State
from lightcycle.domain.work.timestamp import parse_timestamp

_MIN_TIMESTAMP = datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)


class NextStepResolver:
    def __init__(self, store, flow):
        self._store = store
        self._flow = flow

    def _history(self, t):
        return sorted(
            (
                s for s in self._store.steps_at_step(t.stage)
                if s.item == t.item and s.state == State.DONE
            ),
            key=lambda s: (parse_timestamp(s.created_at) or _MIN_TIMESTAMP, node_id_key(s.id)),
        )

    def resolve(self, t, outcome, name):
        transition = self._flow.flow_next(t.stage, outcome, name)
        if transition is None:
            return None
        cap_outcome = self._flow.ci_failed_cap_outcome(t.stage, name)
        prior = 0
        if cap_outcome is not None and outcome == cap_outcome:
            prior = consecutive_outcome_count(self._history(t), outcome)
        transition = self._flow.effective_transition(transition, outcome, prior, name)

        rr_outcome = self._flow.review_rounds_cap_outcome(t.stage, name)
        rr_prior = 0
        if rr_outcome is not None and outcome == rr_outcome:
            rr_prior = consecutive_outcome_count(self._history(t), outcome)
        return self._flow.review_rounds_transition(transition, outcome, rr_prior, name)

    def spec_for(self, t, transition):
        if transition is None:
            return None
        return transition.next_step_spec(t)

    def create(self, t, transition):
        spec = self.spec_for(t, transition)
        return self._store.create_step(**spec.as_kwargs())
