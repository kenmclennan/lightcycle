import unittest

from lightcycle.application.flow import ClaimInput, ClaimStepUseCase
from lightcycle.application.pool import TickInput
from lightcycle.application.pool.github_budget import GithubBudgetUseCase
from lightcycle.application.pool.no_op_gates import NoOpGhCallGate
from lightcycle.application.services.flow import FlowService
from lightcycle.cli import _tick_event_lines
from lightcycle.domain.flow import Flow
from lightcycle.domain.flow.graph import parse_graph
from lightcycle.domain.pool import GithubBudget, github_budget_from_state, github_budget_low
from tests.support.fake_fs import FakeFs
from tests.support.fake_github_budget_status import FakeGithubBudgetStatus
from tests.support.fake_store import FakeStore
from tests.support.step_factory import create_owned_step
from tests.unit.test_flow_usecases import FakeConfig as ClaimConfig
from tests.unit.test_flow_usecases import FakeWorkers as ClaimWorkers
from tests.unit.test_flow_usecases import FakeWorktrees
from tests.unit.test_pool import FakeConfig, FakeSpawner, FakeWorkers, make_tick

RESET = 5000.0


class _Config:
    def __init__(self, reserve=750):
        self._reserve = reserve

    def github_reserve_calls(self):
        return self._reserve


class _HeavyFlow(FlowService):
    def __init__(self, heavy, store):
        super().__init__(FakeFs({}), store)
        self._heavy = set(heavy)
        self.consulted = []

    def is_github_heavy(self, step):
        self.consulted.append(step.id)
        return step.stage in self._heavy


def _state(remaining, reset=RESET):
    return GithubBudget(limit=5000, remaining=remaining, reset=reset, read_at=1.0)


def _budget(status, flow, now=1000.0, reserve=750):
    return GithubBudgetUseCase(status, flow, _Config(reserve), lambda: now)


class TestBudgetRule(unittest.TestCase):
    def _low(self, remaining, now=1000.0, reserve=750, reset=RESET):
        return github_budget_low(GithubBudget(5000, remaining, reset), reserve, now)

    def test_remaining_equal_to_the_reserve_is_not_low(self):
        self.assertFalse(self._low(750))

    def test_remaining_one_below_the_reserve_is_low(self):
        self.assertTrue(self._low(749))

    def test_zero_remaining_at_the_reset_instant_is_not_low(self):
        self.assertFalse(self._low(0, now=RESET))

    def test_zero_remaining_before_the_reset_is_low(self):
        self.assertTrue(self._low(0, now=RESET - 1))

    def test_no_reading_is_not_low(self):
        self.assertFalse(github_budget_low(None, 750, 1000.0))

    def test_a_zero_reserve_never_holds(self):
        self.assertFalse(self._low(0, reserve=0))

    def test_a_state_missing_a_field_is_no_reading(self):
        self.assertIsNone(github_budget_from_state({"limit": 5000, "remaining": 1}))
        self.assertIsNone(github_budget_from_state({}))
        self.assertIsNone(github_budget_from_state(None))


class TestBudgetUseCase(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        self.a = create_owned_step(self.store, "a", stage="watch-ci", role="agent")
        self.b = create_owned_step(self.store, "b", stage="build", role="agent")
        self.c = create_owned_step(self.store, "c", stage="review-code", role="agent")
        self.flow = _HeavyFlow({"watch-ci", "review-code"}, self.store)
        self.ready = self.store.ready_steps()

    def test_held_is_the_heavy_steps_only_while_low(self):
        uc = _budget(FakeGithubBudgetStatus(_state(100)), self.flow)

        self.assertEqual(uc.held(self.ready), {self.a, self.c})

    def test_nothing_is_held_and_the_flow_is_not_consulted_when_not_low(self):
        uc = _budget(FakeGithubBudgetStatus(_state(4000)), self.flow)

        self.assertEqual(uc.held(self.ready), frozenset())
        self.assertEqual(self.flow.consulted, [])

    def test_no_reading_holds_nothing_and_reports_unknown(self):
        uc = _budget(FakeGithubBudgetStatus(), self.flow)

        self.assertEqual(uc.held(self.ready), frozenset())
        self.assertFalse(uc.reading().known)

    def test_a_window_that_has_reset_releases_the_hold(self):
        uc = _budget(FakeGithubBudgetStatus(_state(0, reset=900.0)), self.flow, now=1000.0)

        self.assertEqual(uc.held(self.ready), frozenset())

    def test_a_fresh_reading_at_the_reserve_releases_the_hold(self):
        status = FakeGithubBudgetStatus(_state(100))
        uc = _budget(status, self.flow)
        self.assertEqual(uc.held(self.ready), {self.a, self.c})

        status.save(_state(750))

        self.assertEqual(uc.held(self.ready), frozenset())

    def test_construction_fails_naming_the_key_when_the_reserve_is_missing(self):
        class Missing:
            def github_reserve_calls(self):
                raise RuntimeError("github-reserve-calls")

        with self.assertRaises(RuntimeError):
            GithubBudgetUseCase(FakeGithubBudgetStatus(), self.flow, Missing(), lambda: 0.0)


class TestTickHold(unittest.TestCase):
    def _tick(self, store, status, flow, now=1000.0):
        return make_tick(
            store, FakeWorkers(), FakeSpawner(), FakeConfig(max_agents=4),
            github_budget=_budget(status, flow, now=now), gh_call_gate=NoOpGhCallGate())

    def _store(self):
        store = FakeStore()
        create_owned_step(store, "a", stage="watch-ci", role="heavy-role")
        create_owned_step(store, "b", stage="build", role="agent")
        create_owned_step(store, "c", stage="review-code", role="heavy-role")
        return store

    def test_a_held_step_is_not_spawned_for_and_a_plain_one_is(self):
        store = self._store()
        spawner = FakeSpawner()
        tick = make_tick(
            store, FakeWorkers(), spawner, FakeConfig(max_agents=4),
            github_budget=_budget(
                FakeGithubBudgetStatus(_state(10)),
                _HeavyFlow({"watch-ci", "review-code"}, store)),
            gh_call_gate=NoOpGhCallGate())

        result = tick.execute(TickInput(now=1000.0))

        self.assertEqual(spawner.spawned, ["agent"])
        self.assertEqual(result.spawned, ["agent"])

    def test_with_every_ready_step_held_nothing_is_spawned(self):
        store = FakeStore()
        create_owned_step(store, "a", stage="watch-ci", role="agent")
        spawner = FakeSpawner()
        tick = make_tick(
            store, FakeWorkers(), spawner, FakeConfig(max_agents=4),
            github_budget=_budget(
                FakeGithubBudgetStatus(_state(10)), _HeavyFlow({"watch-ci"}, store)),
            gh_call_gate=NoOpGhCallGate())

        tick.execute(TickInput(now=1000.0))

        self.assertEqual(spawner.spawned, [])

    def test_when_not_low_the_heavy_step_is_spawned_for(self):
        store = FakeStore()
        create_owned_step(store, "a", stage="watch-ci", role="agent")
        spawner = FakeSpawner()
        tick = make_tick(
            store, FakeWorkers(), spawner, FakeConfig(max_agents=4),
            github_budget=_budget(
                FakeGithubBudgetStatus(_state(4000)), _HeavyFlow({"watch-ci"}, store)),
            gh_call_gate=NoOpGhCallGate())

        tick.execute(TickInput(now=1000.0))

        self.assertEqual(spawner.spawned, ["agent"])

    def test_the_run_log_lines_appear_once_on_opening_and_once_on_clearing(self):
        store = FakeStore()
        status = FakeGithubBudgetStatus(_state(10))
        tick = make_tick(
            store, FakeWorkers(), FakeSpawner(), FakeConfig(max_agents=4),
            github_budget=_budget(status, _HeavyFlow(set(), store)),
            gh_call_gate=NoOpGhCallGate())

        first = _tick_event_lines(tick.execute(TickInput(now=1000.0)), "12:00:00")
        second = _tick_event_lines(tick.execute(TickInput(now=1005.0)), "12:00:05")
        status.save(_state(2000))
        third = _tick_event_lines(tick.execute(TickInput(now=1010.0)), "12:00:10")
        fourth = _tick_event_lines(tick.execute(TickInput(now=1015.0)), "12:00:15")

        opened = [l for l in first if "github" in l]
        self.assertEqual(len(opened), 1)
        self.assertIn("github   budget low, 10 remaining, resets at ", opened[0])
        self.assertEqual([l for l in second if "github" in l], [])
        self.assertEqual(
            [l for l in third if "github" in l], ["12:00:10  github   budget recovered"])
        self.assertEqual([l for l in fourth if "github" in l], [])


class TestClaimHold(unittest.TestCase):
    def _claim(self, store, status, heavy, role="agent"):
        flow = _HeavyFlow(heavy, store)
        uc = ClaimStepUseCase(
            store, flow, FakeWorktrees(), ClaimWorkers(), ClaimConfig(),
            _budget(status, flow))
        return uc.execute(ClaimInput(role=role))

    def _store(self):
        store = FakeStore()
        item = store.create_item("i", "a description", workflow="standard", shortcode="GRID")
        self.heavy = store.create_step(stage="open-pr", role="agent", item=item)
        self.plain = store.create_step(stage="build", role="agent", item=item)
        return store

    def test_while_low_the_claim_skips_a_heavy_step_and_takes_the_plain_one(self):
        store = self._store()

        resp = self._claim(store, FakeGithubBudgetStatus(_state(10)), {"open-pr"})

        self.assertEqual(resp.view.step.id, self.plain)

    def test_while_low_a_role_with_only_heavy_steps_claims_nothing(self):
        store = FakeStore()
        item = store.create_item("i", "a description", workflow="standard", shortcode="GRID")
        store.create_step(stage="open-pr", role="agent", item=item)

        self.assertIsNone(self._claim(store, FakeGithubBudgetStatus(_state(10)), {"open-pr"}))

    def test_when_not_low_the_heavy_step_is_claimed_first_as_before(self):
        store = self._store()

        resp = self._claim(store, FakeGithubBudgetStatus(_state(4000)), {"open-pr"})

        self.assertEqual(resp.view.step.id, self.heavy)

    def test_with_no_reading_the_claim_is_unchanged(self):
        store = self._store()

        resp = self._claim(store, FakeGithubBudgetStatus(), {"open-pr"})

        self.assertEqual(resp.view.step.id, self.heavy)


GRAPH = """
entry: build

nodes:
  build   coder
  review  reviewer

edges:
  build   done  review
  review  done
"""


class TestFlowGithubHeavy(unittest.TestCase):
    def _flow(self, reviewer):
        metas = {"coder": {"model": "sonnet"}, "reviewer": reviewer}
        return Flow.from_graph(parse_graph(GRAPH), metas)

    def test_a_step_declaring_github_heavy_is_marked(self):
        flow = self._flow({"model": "sonnet", "github": "heavy"})

        self.assertTrue(flow.step_def("review").github_heavy)
        self.assertFalse(flow.step_def("build").github_heavy)

    def test_a_step_without_the_key_is_not_marked(self):
        flow = self._flow({"model": "sonnet"})

        self.assertFalse(flow.step_def("review").github_heavy)


if __name__ == "__main__":
    unittest.main()
