import unittest

from lightcycle.application.flow.route_step import RouteStepService
from tests.support.fake_store import FakeStore
from tests.support.step_factory import create_owned_step


class TestRouteStepService(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        self.step = create_owned_step(self.store, "build: x", stage="build", role="agent")

    def test_routing_to_human_leaves_the_step_waiting(self):
        RouteStepService(self.store).route(self.step, "human")
        self.assertEqual(self.store.get_node(self.step).state, "waiting")

    def test_routing_to_an_agent_role_queues_the_step(self):
        RouteStepService(self.store).route(self.step, "human")
        RouteStepService(self.store).route(self.step, "reviewer")
        self.assertEqual(self.store.get_node(self.step).state, "queued")

    def test_the_old_role_label_is_dropped_and_the_new_one_added(self):
        RouteStepService(self.store).route(self.step, "human")
        node = self.store.get_node(self.step)
        self.assertEqual(node.role, "human")
        self.assertNotIn("for:agent", self.store.labels_of(self.step))

    def test_the_step_ends_unassigned(self):
        self.store.claim_ready("agent", "w1")
        RouteStepService(self.store).route(self.step, "human")
        self.assertFalse(self.store.get_node(self.step).claimed_by)

    def test_routing_to_the_role_it_already_has_adds_no_duplicate_label(self):
        RouteStepService(self.store).route(self.step, "agent")
        self.assertEqual([l for l in self.store.labels_of(self.step) if l == "for:agent"], ["for:agent"])


if __name__ == "__main__":
    unittest.main()
