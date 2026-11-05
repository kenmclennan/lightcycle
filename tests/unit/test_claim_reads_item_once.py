import pathlib
import unittest
from unittest import mock

from lightcycle.application.flow import (
    ClaimInput, ClaimStepUseCase, CompleteInput, CompleteStepUseCase,
)
from lightcycle.application.work.item_outputs import ItemOutputs
from lightcycle import config as config_module
from lightcycle.config import Config
from tests.support.fake_github_budget import FakeGithubBudget
from tests.support.fake_store import FakeStore
from tests.unit.test_flow_usecases import (
    SPEC_METAS, FakeConfig, FakeWorkers, FakeWorktrees, flow_for,
)
from tests.unit.test_step_model import METAS


class _Counting:
    def __init__(self, store):
        self._store = store
        self.calls = {"children": 0, "step_stamps": 0, "get_item": 0}

    def children(self, item_id):
        self.calls["children"] += 1
        return self._store.children(item_id)

    def step_stamps(self, item_id):
        self.calls["step_stamps"] += 1
        return self._store.step_stamps(item_id)

    def get_item(self, item_id):
        self.calls["get_item"] += 1
        return self._store.get_item(item_id)

    def __getattr__(self, name):
        return getattr(self._store, name)


def _claim_counts(step_count):
    store = FakeStore()
    item = store.create_item("t", "the brief", workflow="spec-driven", shortcode="APP")
    for _ in range(step_count - 1):
        sid = store.create_step(stage="build", role="agent", item=item)
        store.claim_ready("agent", "x")
        store.complete_node(sid, "done")
    store.create_step(stage="build", role="agent", item=item)
    counting = _Counting(store)
    uc = ClaimStepUseCase(
        counting, flow_for(METAS, counting), FakeWorktrees(), FakeWorkers(), FakeConfig(),
        FakeGithubBudget(),
    )
    uc.execute(ClaimInput(role="agent"))
    return dict(counting.calls)


class TestClaimReadsAnItemsStepsOnce(unittest.TestCase):
    def test_the_read_counts_do_not_grow_with_the_step_count(self):
        small = _claim_counts(5)
        large = _claim_counts(50)

        self.assertEqual(small, large)

    def test_the_claim_reads_step_stamps_exactly_once(self):
        self.assertEqual(_claim_counts(5)["step_stamps"], 1)


class TestReadingScope(unittest.TestCase):
    def _rig(self):
        store = FakeStore()
        flow = flow_for(METAS, store)
        item = store.create_item("t", "the brief", workflow="spec-driven", shortcode="APP")
        step = store.create_step(stage="build", role="agent", item=item)
        return store, ItemOutputs(store, flow), item, step

    def test_stamps_give_the_same_outputs_as_the_step_rows(self):
        store, outputs, item, step = self._rig()
        store.add_artifact(step, "X", "v1")
        store.claim_ready("agent", "x")
        store.complete_node(step, "done")
        p1 = store.open_pass(item)
        store.set_step_pass(step, p1)
        review = store.create_step(stage="review", role="agent", item=item)
        p2 = store.open_pass(item)
        store.set_step_pass(review, p2)
        later = store.create_step(stage="build", role="agent", item=item)
        store.set_step_pass(later, p2)
        store.add_artifact(later, "X", "v2")
        node = store.get_node(later)

        facts = outputs._facts(item)

        children = {c.id: c for c in store.children(item) if c.type == "step"}
        self.assertEqual(set(facts), set(children))
        for sid, fact in facts.items():
            child = children[sid]
            self.assertEqual(fact.pass_id, child.pass_id)
            self.assertEqual(fact.at, child.closed_at or child.created_at)
            self.assertEqual(
                fact.declared, outputs._declared(store.item_workflow(item), child.stage))
        self.assertEqual(facts[step].declared, frozenset({"X"}))
        self.assertEqual(facts[review].declared, frozenset())
        self.assertIsNotNone(children[step].closed_at)
        self.assertIsNone(children[later].closed_at)
        self.assertEqual(outputs.for_reader(node).types, {"X"})
        self.assertEqual(outputs.present_types(node), {"X"} | set(store.present_types(node)))

    def test_outside_reading_a_later_read_sees_the_closed_step(self):
        store, outputs, item, step = self._rig()
        before = outputs._facts(item)[step].at
        store._get(step)["closed_at"] = "2099-01-01T00:00:00+00:00"

        self.assertNotEqual(outputs._facts(item)[step].at, before)

    def test_inside_reading_a_later_read_sees_the_first_snapshot(self):
        store, outputs, item, step = self._rig()
        with outputs.reading():
            before = outputs._facts(item)[step].at
            store._get(step)["closed_at"] = "2099-01-01T00:00:00+00:00"
            self.assertEqual(outputs._facts(item)[step].at, before)
        self.assertNotEqual(outputs._facts(item)[step].at, before)

    def test_nested_reading_keeps_the_memo_until_the_outermost_exits(self):
        store, outputs, item, step = self._rig()
        with outputs.reading():
            with outputs.reading():
                before = outputs._facts(item)[step].at
            store._get(step)["closed_at"] = "2099-01-01T00:00:00+00:00"
            self.assertEqual(outputs._facts(item)[step].at, before)


class TestCompletionScope(unittest.TestCase):
    def test_completion_drops_the_memo_and_a_later_read_sees_the_close(self):
        store = FakeStore()
        flow = flow_for(METAS, store)
        item = store.create_item("t", "the brief", workflow="spec-driven", shortcode="APP")
        sid = store.create_step(stage="build", role="agent", item=item)
        store.claim_ready("agent", "x")
        store.add_artifact(sid, "X", "v1")
        uc = CompleteStepUseCase(store, flow, FakeWorktrees(), FakeConfig())
        before = ItemOutputs(store, flow)._facts(item)[sid].at

        uc.execute(CompleteInput(step=sid, outcome="done"))

        self.assertIsNone(uc._outputs._facts_memo)
        self.assertNotEqual(uc._outputs._facts(item)[sid].at, before)


class TestClaimPaths(unittest.TestCase):
    def _uc(self, store, metas):
        return ClaimStepUseCase(
            store, flow_for(metas, store), FakeWorktrees(), FakeWorkers(), FakeConfig(),
            FakeGithubBudget(),
        )

    def test_a_missing_input_parks_the_step_with_the_scope_open(self):
        store = FakeStore()
        item = store.create_item("t", "the brief", workflow="standard", shortcode="APP")
        sid = store.create_step(stage="build", role="agent", item=item)
        counting = _Counting(store)
        uc = ClaimStepUseCase(
            counting, flow_for(SPEC_METAS, counting), FakeWorktrees(), FakeWorkers(),
            FakeConfig(), FakeGithubBudget(),
        )

        resp = uc.execute(ClaimInput(role="agent"))

        self.assertIsNone(resp)
        node = store.get_node(sid)
        self.assertEqual(node.role, "human")
        self.assertIn("missing required input(s): spec", node.park.needs or "")
        self.assertEqual(counting.calls["step_stamps"], 1)
        self.assertEqual(counting.calls["children"], 0)

    def test_a_claim_after_a_close_sees_the_close(self):
        store = FakeStore()
        item = store.create_item("t", "the brief", workflow="spec-driven", shortcode="APP")
        first = store.create_step(stage="build", role="agent", item=item)
        uc = self._uc(store, METAS)
        uc.execute(ClaimInput(role="agent"))
        before = ItemOutputs(store, uc._flow)._facts(item)[first].at
        store.add_artifact(first, "X", "v1")
        CompleteStepUseCase(store, uc._flow, FakeWorktrees(), FakeConfig()).execute(
            CompleteInput(step=first, outcome="done"))
        seen = {}
        real = ItemOutputs._read_facts

        def spy(outputs, item_id):
            facts = real(outputs, item_id)
            seen.update(facts)
            return facts

        with mock.patch.object(ItemOutputs, "_read_facts", spy):
            resp = uc.execute(ClaimInput(role="agent"))

        self.assertIsNotNone(resp)
        self.assertNotEqual(seen[first].at, before)
        self.assertEqual(seen[first].at, store.get_node(first).closed_at)


class TestPromptsRootIsComputedOnce(unittest.TestCase):
    def test_prompts_root_makes_no_resolve_call(self):
        expected = str(pathlib.Path(config_module.__file__).resolve().parent / "prompts")
        with mock.patch.object(pathlib.Path, "resolve", side_effect=AssertionError("resolve")):
            self.assertEqual(Config.prompts_root(None), expected)


if __name__ == "__main__":
    unittest.main()
