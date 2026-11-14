import unittest

from lightcycle.application.flow.cap_restart import stage_escalation_firing_ids
from lightcycle.application.services.flow import FlowService
from lightcycle.domain.flow.flow import since_last_firing
from lightcycle.domain.work import State
from tests.support.fake_fs import FakeFs
from tests.support.fake_store import FakeStore

METAS = {"coder": {"model": "sonnet"}, "reviewer": {"model": "sonnet"}}

GRAPH_CUT = (
    "entry: build\n\nnodes:\n  build   coder\n  review  reviewer\n\n"
    "edges:\n  build   done      review\n  review  rejected  build\n  review  done      ship\n\n"
    "hooks:\n  review_rounds_cap  review  rejected  escalate-step\n"
)

GRAPH_ROUTED = (
    "entry: build\n\nnodes:\n  build   coder\n  review  reviewer\n\n"
    "edges:\n  build   done      review\n  review  rejected  escalate-step\n  review  done      ship\n\n"
    "hooks:\n  review_rounds_cap  review  rejected  escalate-step\n"
)


class TestStageEscalationFiringIds(unittest.TestCase):
    def _setup(self, graph):
        store = FakeStore()
        item = store.create_item("st", "a description", workflow="spec-driven", shortcode="GRID")
        flow = FlowService(FakeFs(METAS, workflow=graph), store).load_flow()
        return store, item, flow

    def _close(self, store, item, outcome):
        sid = store.create_step(stage="review", role="agent", item=item)
        store.complete_node(sid, outcome)
        return sid

    def _history(self, store, item):
        return [
            s for s in store.steps_at_step("review")
            if s.item == item and s.state == State.DONE
        ]

    def test_only_firing_ids_with_an_escalation_successor_are_returned(self):
        store, item, flow = self._setup(GRAPH_CUT)
        first = self._close(store, item, "rejected")
        store.create_step(stage="escalate-step", role="human", item=item, previous=first)
        unescalated = self._close(store, item, "rejected")
        last = self._close(store, item, "done")

        history = self._history(store, item)
        firing = stage_escalation_firing_ids(store, flow, item, "review", history)

        self.assertEqual(firing, {first})
        self.assertNotIn(unescalated, firing)
        self.assertEqual(
            [s.id for s in since_last_firing(history, firing)], [unescalated, last])

    def test_an_escalation_step_of_another_item_is_not_a_firing(self):
        store, item, flow = self._setup(GRAPH_CUT)
        other = store.create_item("other", "a description", workflow="spec-driven", shortcode="GRID")
        first = self._close(store, item, "rejected")
        store.create_step(stage="escalate-step", role="human", item=other, previous=first)

        firing = stage_escalation_firing_ids(
            store, flow, item, "review", self._history(store, item))

        self.assertEqual(firing, set())

    def test_a_stage_that_routes_the_cap_outcome_to_its_escalate_stage_is_never_cut(self):
        store, item, flow = self._setup(GRAPH_ROUTED)
        first = self._close(store, item, "rejected")
        escalation = store.create_step(
            stage="escalate-step", role="human", item=item, previous=first)
        self.assertEqual(store.get_node(escalation).previous_step, first)

        history = self._history(store, item)
        firing = stage_escalation_firing_ids(store, flow, item, "review", history)

        self.assertEqual(firing, set())
        self.assertEqual(since_last_firing(history, firing), history)
