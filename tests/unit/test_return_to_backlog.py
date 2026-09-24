import unittest

from lightcycle.application.errors import UseCaseError
from lightcycle.application.flow import BlockInput, BlockStepUseCase
from lightcycle.application.services.flow import FlowService
from lightcycle.application.work.activate_item import ActivateItemInput, ActivateItemUseCase
from lightcycle.application.work.item_partition import is_backlogged_item
from lightcycle.application.work.return_to_backlog import (
    ReturnToBacklogInput,
    ReturnToBacklogUseCase,
)
from lightcycle.domain.runs import RunState
from lightcycle.domain.work import State
from tests.support.fake_fs import FakeFs, graph_text_from_metas
from tests.support.fake_store import FakeStore


def _item(store, steps=1):
    item = store.create_item("an item", "a description")
    pid = store.open_pass(item)
    run = store.open_run(item, pid, "code")
    step_ids = [store.create_step(step="build", role="agent", parent=item) for _ in range(steps)]
    return item, pid, run, step_ids


def _backlog(store, item):
    return ReturnToBacklogUseCase(store).execute(ReturnToBacklogInput(item=item))


def _refusal(test, store, item):
    with test.assertRaises(UseCaseError) as cm:
        _backlog(store, item)
    return str(cm.exception)


class TestReturnToBacklogAccepts(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()

    def test_a_queued_step_is_removed_and_the_item_is_backlogged(self):
        item, pid, run, (step,) = _item(self.store)
        resp = _backlog(self.store, item)
        self.assertEqual(resp.removed, (step,))
        self.assertEqual(self.store.children(item), [])
        self.assertEqual(self.store.get_node(item).state, State.BACKLOGGED)
        self.assertTrue(is_backlogged_item(self.store, self.store.get_node(item)))

    def test_a_parked_step_is_removed_like_a_queued_one(self):
        item, pid, run, (queued, parked) = _item(self.store, steps=2)
        BlockStepUseCase(self.store).execute(
            BlockInput(step=parked, needs="a decision", reason="needed one")
        )
        self.assertEqual(self.store.get_node(parked).state, State.WAITING)
        resp = _backlog(self.store, item)
        self.assertEqual(set(resp.removed), {queued, parked})
        self.assertEqual(self.store.children(item), [])

    def test_done_steps_open_pass_and_open_run_are_left_alone(self):
        item, pid, run, (done, open_step) = _item(self.store, steps=2)
        self.store.complete_node(done, "finished")
        resp = _backlog(self.store, item)
        self.assertEqual(resp.removed, (open_step,))
        self.assertEqual([c.id for c in self.store.children(item)], [done])
        self.assertEqual(self.store.current_pass(item).id, pid)
        self.assertEqual([r.id for r in self.store.open_runs_of(item)], [run])

    def test_a_closed_run_with_a_branch_does_not_refuse(self):
        item, pid, run, _ = _item(self.store)
        self.store.set_branch(run, "feat/old")
        self.store.close_run(run, RunState.MERGED)
        self.store.open_run(item, pid, "review")
        _backlog(self.store, item)
        self.assertEqual(self.store.children(item), [])

    def test_an_item_with_its_own_dependency_accepts_and_is_listed_as_backlogged(self):
        item, pid, run, _ = _item(self.store)
        blocker = self.store.create_item("blocker", "a description")
        self.store.dep_add(item, blocker)
        _backlog(self.store, item)
        self.assertEqual(self.store.children(item), [])
        self.assertTrue(is_backlogged_item(self.store, self.store.get_node(item)))


class TestReturnToBacklogRefuses(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()

    def test_a_claimed_step_refuses_and_is_named(self):
        item, pid, run, (step,) = _item(self.store)
        self.store.claim_ready("agent", "worker1", item=item)
        self.assertEqual(self.store.get_node(step).state, State.RUNNING)
        msg = _refusal(self, self.store, item)
        self.assertIn(step, msg)
        self.assertIn("wait for it, or park it", msg)
        self.assertEqual([c.id for c in self.store.children(item)], [step])

    def test_a_claimed_step_beside_an_unclaimed_one_refuses_and_removes_nothing(self):
        item, pid, run, (a, b) = _item(self.store, steps=2)
        self.store.claim_ready("agent", "worker1", item=item)
        states = {s: self.store.get_node(s).state for s in (a, b)}
        held = [s for s, st in states.items() if st == State.RUNNING]
        free = [s for s, st in states.items() if st != State.RUNNING]
        self.assertEqual((len(held), len(free)), (1, 1))
        msg = _refusal(self, self.store, item)
        self.assertIn(held[0], msg)
        self.assertNotIn(free[0], msg)
        self.assertEqual({c.id for c in self.store.children(item)}, {a, b})

    def test_a_run_with_a_branch_only_refuses(self):
        item, pid, run, _ = _item(self.store)
        self.store.set_branch(run, "feat/x")
        msg = _refusal(self, self.store, item)
        self.assertIn(run, msg)
        self.assertIn("feat/x", msg)
        self.assertIn("work in flight", msg)
        self.assertIn("lc close %s" % item, msg)
        self.assertEqual(len(self.store.children(item)), 1)

    def test_a_run_with_a_pr_only_refuses(self):
        item, pid, run, _ = _item(self.store)
        self.store.set_pr(run, "https://github.com/o/r/pull/1")
        msg = _refusal(self, self.store, item)
        self.assertIn("https://github.com/o/r/pull/1", msg)
        self.assertIn("lc close %s" % item, msg)
        self.assertEqual(len(self.store.children(item)), 1)

    def test_a_closed_item_refuses_naming_reopen(self):
        item, pid, run, _ = _item(self.store)
        self.store.complete_node(item, "dropped", "abandoned")
        msg = _refusal(self, self.store, item)
        self.assertIn("lc reopen %s" % item, msg)

    def test_an_already_backlogged_item_refuses(self):
        item = self.store.create_item("an item", "a description")
        self.assertIn("already in the backlog", _refusal(self, self.store, item))

    def test_a_stepless_item_with_a_pr_gets_the_in_flight_refusal(self):
        item, pid, run, (step,) = _item(self.store)
        self.store.delete(step)
        self.store.set_pr(run, "https://github.com/o/r/pull/2")
        msg = _refusal(self, self.store, item)
        self.assertIn("work in flight", msg)
        self.assertNotIn("already in the backlog", msg)

    def test_every_applicable_reason_is_listed_one_per_line(self):
        item, pid, run, (step,) = _item(self.store)
        self.store.claim_ready("agent", "worker1", item=item)
        self.store.set_branch(run, "feat/x")
        self.store.set_pr(run, "https://github.com/o/r/pull/3")
        lines = _refusal(self, self.store, item).splitlines()
        self.assertEqual(len(lines), 2)
        self.assertIn(step, lines[0])
        self.assertIn("feat/x", lines[1])
        self.assertIn("pull/3", lines[1])

    def test_a_step_is_refused(self):
        item, pid, run, (step,) = _item(self.store)
        self.assertIn("not an item", _refusal(self, self.store, step))

    def test_an_unknown_id_is_refused(self):
        self.assertIn("no such node", _refusal(self, self.store, "NOPE-1"))


class TestReturnToBacklogRoundTrip(unittest.TestCase):
    def test_reactivation_reuses_the_open_pass_and_run(self):
        store = FakeStore()
        metas = {"coder": {"model": "sonnet", "step": "build", "routes": {"done": "review"}}}
        flow = FlowService(
            FakeFs(metas, workflow=graph_text_from_metas(metas, entry="build")), store
        )
        item = store.create_item("add refunds", "a description")
        activate = ActivateItemUseCase(store, flow, None, None)
        first = activate.execute(ActivateItemInput(item=item, workflow="standard")).step
        _backlog(store, item)
        self.assertEqual(store.get_node(item).state, State.BACKLOGGED)
        second = activate.execute(ActivateItemInput(item=item)).step
        self.assertNotEqual(first, second)
        self.assertEqual(len(store.open_runs_of(item)), 1)
        self.assertEqual(len([p for p in store.passes_of(item)]), 1)
