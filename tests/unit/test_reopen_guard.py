import unittest

from lightcycle.application.errors import UseCaseError
from lightcycle.application.flow.park_step import ParkInput, ParkStepUseCase
from lightcycle.application.flow.route_step import RouteStepService
from lightcycle.application.flow.unblock_step import UnblockInput, UnblockStepUseCase
from tests.support.fake_store import FakeStore


class _Flow:
    def flow_for(self, node):
        from types import SimpleNamespace
        return SimpleNamespace(step_def=lambda stage: SimpleNamespace(owner="agent"))


class _Spin:
    def update(self, fn):
        pass


class _Base(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        self.item = self.store.create_item("x", "d", shortcode="OWN")
        self.a = self.store.create_step(stage="write-code", role="agent", item=self.item)
        self.store.claim_ready("agent", "w1")
        self.store.complete_step_atomic(self.a, "done", "w1", None)
        self.b = self.store.create_step(
            stage="code-open-pr", role="agent", item=self.item, previous=self.a)

    def snapshot(self):
        n = self.store.get_node(self.a)
        return (
            n.state, n.notes, n.park.as_dict(), sorted(self.store.labels_of(self.a)),
            list(self.store._history.get(self.a, [])),
        )

    def refused(self, fn, *ids):
        before = self.snapshot()
        with self.assertRaises(UseCaseError) as cm:
            fn()
        for i in ids:
            self.assertIn(i, str(cm.exception))
        self.assertIn("lc rm", str(cm.exception))
        self.assertEqual(self.snapshot(), before)


class TestRefusalOnEachRoute(_Base):
    def test_park_is_refused_and_names_the_successor(self):
        uc = ParkStepUseCase(self.store)
        self.refused(lambda: uc.execute(ParkInput(self.a, "why", "what")), self.b)

    def test_park_once_is_refused(self):
        uc = ParkStepUseCase(self.store)
        self.refused(lambda: uc.execute_once(ParkInput(self.a, "why", "what")), self.b)

    def test_unblock_is_refused_and_names_the_successor(self):
        uc = UnblockStepUseCase(self.store, _Flow(), spin_port=_Spin())
        self.refused(lambda: uc.execute(UnblockInput(self.a)), self.b)

    def test_route_is_refused_for_human_and_agent(self):
        svc = RouteStepService(self.store)
        self.refused(lambda: svc.route(self.a, "human"), self.b)
        self.refused(lambda: svc.route(self.a, "agent"), self.b)

    def test_two_open_successors_are_both_named(self):
        c = self.store.create_step(
            stage="poll-ci", role="agent", item=self.item, previous=self.a)
        self.refused(lambda: RouteStepService(self.store).route(self.a, "human"), self.b, c)

    def test_a_closed_and_an_open_successor_names_only_the_open_one(self):
        c = self.store.create_step(
            stage="poll-ci", role="agent", item=self.item, previous=self.a)
        self.store.claim_ready("agent", "w2")
        self.store.complete_step_atomic(self.b, "done", "w2", None)
        with self.assertRaises(UseCaseError) as cm:
            RouteStepService(self.store).route(self.a, "human")
        self.assertIn(c, str(cm.exception))
        self.assertNotIn(self.b, str(cm.exception))


class TestAllowedOnceClear(_Base):
    def close_successor(self):
        self.store.claim_ready("agent", "w2")
        self.store.complete_step_atomic(self.b, "done", "w2", None)

    def test_park_succeeds_once_the_successor_is_closed(self):
        self.close_successor()
        ParkStepUseCase(self.store).execute(ParkInput(self.a, "why", "what"))
        self.assertEqual(self.store.get_node(self.a).state, "waiting")

    def test_unblock_succeeds_once_the_successor_is_closed(self):
        self.close_successor()
        ParkStepUseCase(self.store).execute(ParkInput(self.a, "why", "what"))
        UnblockStepUseCase(self.store, _Flow(), spin_port=_Spin()).execute(UnblockInput(self.a))
        self.assertEqual(self.store.get_node(self.a).state, "queued")

    def test_a_running_step_with_a_stray_successor_is_not_guarded(self):
        c = self.store.create_step(stage="x", role="agent", item=self.item)
        self.store.create_step(stage="y", role="agent", item=self.item, previous=c)
        self.store.claim_ready("agent", "w3")
        RouteStepService(self.store).route(c, "human")
        self.assertEqual(self.store.get_node(c).state, "waiting")


if __name__ == "__main__":
    unittest.main()
