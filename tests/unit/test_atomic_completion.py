import datetime
import unittest

from lightcycle.application.flow import CompleteInput, CompleteStepUseCase
from lightcycle.application.pool.close_stranded_items import CloseStrandedItemsUseCase
from lightcycle.application.services.flow import FlowService
from lightcycle.application.work.close_item import (
    RELEASE_PENDING_LABEL, TEARDOWN_REFUSED_ARTIFACT, CloseItemInput, CloseItemUseCase,
)
from lightcycle.domain.work import State
from lightcycle.ports.git import GitReadError
from tests.support.fake_fs import FakeFs
from tests.support.fake_store import FakeStore
from tests.unit.test_pool import FakeWorkers, make_sweep
from tests.unit.test_release_interrupted_runs import _Fixture

METAS = {"finaliser": {"model": "sonnet", "step": "finalise"}}


class StubWorktrees:
    def __init__(self, findings=None):
        self.findings = list(findings or [])
        self.guard_calls = []
        self.removed = []

    def teardown_refusals(self, item, merged_prs=frozenset()):
        self.guard_calls.append(item)
        return list(self.findings)

    def remove(self, item):
        self.removed.append(item)

    def release_run(self, run):
        self.removed.append(run.id)


class ItemCloseFault(FakeStore):
    fail_for = None

    def complete_node(self, tid, reason, disposition=None, note=None):
        if tid == self.fail_for:
            raise RuntimeError("killed")
        return super().complete_node(tid, reason, disposition, note)


def _complete(store, worktrees, step, outcome="done", note=None):
    uc = CompleteStepUseCase(store, FlowService(FakeFs(METAS), store), worktrees)
    return uc.execute(CompleteInput(step=step, outcome=outcome, note=note))


def _world(store=None, worktrees=None):
    store = store or FakeStore()
    item = store.create_item("story", "a description")
    step = store.create_step(stage="finalise", role="agent", item=item)
    store.update_state(step, State.RUNNING)
    store.assign(step, "sp-1")
    return store, worktrees or StubWorktrees(), item, step


def _strand(store, item_title="stranded"):
    item = store.create_item(item_title, "a description")
    step = store.create_step(stage="finalise", role="agent", item=item)
    store.complete_node(step, "done")
    return item, step


class TestCompletionIsOneTransaction(unittest.TestCase):
    def test_a_fault_in_the_item_close_leaves_the_step_claimed_and_nothing_written(self):
        store = ItemCloseFault()
        store, wt, item, step = _world(store)
        store.fail_for = item

        with self.assertRaises(RuntimeError):
            _complete(store, wt, step, note="the report")

        self.assertEqual(store.get_node(step).state, State.RUNNING)
        self.assertEqual(store.get_node(step).claimed_by, "sp-1")
        self.assertIsNone(store.get_node(step).report)
        self.assertNotEqual(store.get_node(item).state, State.DONE)
        self.assertEqual([a for a in store.item_artifacts(item)
                          if a.type == TEARDOWN_REFUSED_ARTIFACT], [])

        store.fail_for = None
        _complete(store, wt, step, note="the report")

        self.assertEqual(store.get_node(step).state, State.DONE)
        self.assertEqual(store.get_node(item).state, State.DONE)

    def test_step_and_item_are_both_done_once_lc_done_returns(self):
        store, wt, item, step = _world()

        _complete(store, wt, step)

        self.assertEqual(store.get_node(step).state, State.DONE)
        self.assertEqual(store.get_node(item).state, State.DONE)
        self.assertEqual(wt.removed, [item])

    def test_the_item_stays_done_when_the_sweep_kills_the_worker_after_lc_done(self):
        store, wt, item, step = _world()
        workers = FakeWorkers(
            workers=[{"spawnid": "sp-1", "pid": 111, "step": step, "started": 100}],
            alive_pids={111},
        )

        _complete(store, wt, step)
        result = make_sweep(store, workers).execute(now=1000, max_boot=120, stall_seconds=1800)

        self.assertEqual(result.killed, ["sp-1"])
        self.assertEqual(workers.killed, [111])
        self.assertEqual(store.get_node(step).state, State.DONE)
        self.assertEqual(store.get_node(item).state, State.DONE)

    def test_a_successful_close_removes_the_teardown_refused_artifact(self):
        store, wt, item, step = _world(worktrees=StubWorktrees(["dirty"]))
        _complete(store, wt, step)
        self.assertTrue([a for a in store.item_artifacts(item)
                         if a.type == TEARDOWN_REFUSED_ARTIFACT])

        wt.findings = []
        CloseItemUseCase(store, wt).execute(
            CloseItemInput(item=item, reason="done", disposition="completed"))

        self.assertEqual([a for a in store.item_artifacts(item)
                          if a.type == TEARDOWN_REFUSED_ARTIFACT], [])
        self.assertEqual(store.get_node(item).state, State.DONE)
        self.assertNotIn(RELEASE_PENDING_LABEL, store.labels_of(item))


class TestRepeatedCompletion(unittest.TestCase):
    def test_a_repeat_with_the_same_outcome_writes_the_cut_off_report(self):
        store, wt, item, step = _world()
        store.complete_step_atomic(step, "done", "sp-1", None)
        self.assertIsNone(store.get_node(step).report)

        _complete(store, wt, step, note="the report")

        node = store.get_node(step)
        self.assertEqual(node.report, "the report")
        self.assertEqual((node.notes or "").splitlines().count("outcome: done"), 1)
        self.assertEqual(store.get_node(item).state, State.DONE)

    def test_a_repeat_adds_no_second_outcome_note_and_keeps_an_existing_report(self):
        store, wt, item, step = _world()
        _complete(store, wt, step, note="first")
        _complete(store, wt, step, note="second")

        node = store.get_node(step)
        self.assertEqual(node.report, "first")
        self.assertEqual((node.notes or "").splitlines().count("outcome: done"), 1)

    def test_a_repeat_with_a_different_outcome_changes_nothing(self):
        store, wt, item, step = _world()
        store.complete_step_atomic(step, "done", "sp-1", None)

        _complete(store, wt, step, outcome="other", note="x")

        self.assertIsNone(store.get_node(step).report)
        self.assertNotEqual(store.get_node(item).state, State.DONE)


class TestStrandedItems(unittest.TestCase):
    def test_a_stranded_item_is_closed_with_the_guard_applied(self):
        store = FakeStore()
        wt = StubWorktrees()
        item, _ = _strand(store)

        resp = CloseStrandedItemsUseCase(store, wt).execute()

        self.assertEqual(resp.closed, [item])
        self.assertEqual(store.get_node(item).state, State.DONE)
        self.assertEqual(wt.guard_calls, [item])
        self.assertEqual(wt.removed, [item])

    def test_an_item_with_an_unfinished_child_is_never_closed(self):
        for state, role in ((State.WAITING, "human"), (State.QUEUED, "agent"),
                            (State.RUNNING, "agent"), (State.BLOCKED, "agent")):
            with self.subTest(state=state):
                store = FakeStore()
                wt = StubWorktrees()
                item, _ = _strand(store)
                open_step = store.create_step(stage="next", role=role, item=item)
                store.update_state(open_step, state)

                resp = CloseStrandedItemsUseCase(store, wt).execute()

                self.assertEqual(resp.closed, [])
                self.assertEqual(wt.guard_calls, [])
                self.assertNotEqual(store.get_node(item).state, State.DONE)

    def test_a_reopened_item_is_not_closed_again(self):
        store = FakeStore()
        wt = StubWorktrees()
        item, _ = _strand(store)
        store.complete_node(item, "done", "completed")
        store.reopen(item)

        resp = CloseStrandedItemsUseCase(store, wt).execute()

        self.assertEqual(resp.closed, [])

    def test_the_done_entry_boundary_is_inclusive(self):
        for delta, stranded in ((0, False), (-1, True)):
            with self.subTest(delta=delta):
                store = FakeStore()
                wt = StubWorktrees()
                item, step = _strand(store)
                closed_at = store.get_node(step).closed_at
                store._history[item] = [("done", _shift(closed_at, delta))]

                resp = CloseStrandedItemsUseCase(store, wt).execute()

                self.assertEqual(resp.closed == [item], stranded)

    def test_a_refused_recovery_reparks_the_newest_child_and_is_not_retried(self):
        store = FakeStore()
        wt = StubWorktrees(["unmerged commits on feat/x"])
        item, step = _strand(store)

        resp = CloseStrandedItemsUseCase(store, wt).execute()

        self.assertEqual(resp.refused, [(item, "unmerged commits on feat/x")])
        parked = store.get_node(step)
        self.assertEqual(parked.state, State.WAITING)
        self.assertIn("unmerged commits on feat/x", parked.park.reason)
        self.assertIn("lc done %s" % step, parked.park.needs)

        CloseStrandedItemsUseCase(store, wt).execute()

        self.assertEqual(wt.guard_calls, [item])

    def test_a_mixed_batch_is_reported_per_item(self):
        store = FakeStore()
        good, _ = _strand(store, "good")
        refused, _ = _strand(store, "refused")
        waiting, _ = _strand(store, "waiting")
        parked = store.create_step(stage="next", role="human", item=waiting)
        store.update_state(parked, State.WAITING)

        class PerItem(StubWorktrees):
            def teardown_refusals(inner, item, merged_prs=frozenset()):
                inner.guard_calls.append(item)
                return ["dirty"] if item == refused else []

        resp = CloseStrandedItemsUseCase(store, PerItem()).execute()

        self.assertEqual(resp.closed, [good])
        self.assertEqual(resp.refused, [(refused, "dirty")])
        self.assertNotIn(waiting, [i for i, _ in resp.refused] + resp.closed)

    def test_a_cascade_close_refused_on_the_last_step_is_retried_by_the_recovery(self):
        store, wt, item, step = _world(worktrees=StubWorktrees(["dirty"]))
        resp = _complete(store, wt, step)
        self.assertIn("dirty", resp.teardown_refusal)
        self.assertEqual(store.get_node(step).state, State.DONE)
        self.assertNotEqual(store.get_node(item).state, State.DONE)

        refusal = CloseStrandedItemsUseCase(store, wt).execute()

        self.assertEqual(refusal.refused, [(item, "dirty")])
        self.assertEqual(store.get_node(step).state, State.WAITING)

        wt.findings = []
        _complete(store, wt, step)

        self.assertEqual(store.get_node(item).state, State.DONE)


class TestReleasePendingMarker(unittest.TestCase):
    def test_a_closed_item_with_a_cut_off_release_is_released_and_unmarked(self):
        fx = _Fixture()
        fx.store.complete_node(fx.step, "done")
        fx.store.complete_node(fx.item, "done", "completed")
        fx.store.label_add(fx.item, RELEASE_PENDING_LABEL)

        fx.use_case.execute()

        self.assertEqual(len(fx.removals()), 1)
        self.assertNotIn(RELEASE_PENDING_LABEL, fx.store.labels_of(fx.item))

    def test_a_failing_release_keeps_the_marker(self):
        fx = _Fixture()
        fx.store.complete_node(fx.step, "done")
        fx.store.complete_node(fx.item, "done", "completed")
        fx.store.label_add(fx.item, RELEASE_PENDING_LABEL)

        def boom(run):
            raise GitReadError("no")

        fx.worktrees.release_interrupted = boom
        result = fx.use_case.execute()

        self.assertEqual(len(result.failed), 1)
        self.assertIn(RELEASE_PENDING_LABEL, fx.store.labels_of(fx.item))

    def test_a_run_sharing_a_branch_with_an_open_run_is_not_released(self):
        fx = _Fixture()
        fx.store.complete_node(fx.step, "done")
        fx.store.complete_node(fx.item, "done", "completed")
        fx.store.label_add(fx.item, RELEASE_PENDING_LABEL)
        pid = fx.store.open_pass(fx.item)
        other = fx.store.open_run(fx.item, pid, "code")
        fx.store.set_branch(other, fx.run.branch)

        fx.use_case.execute()

        self.assertEqual(fx.removals(), [])

    def test_a_successful_close_leaves_no_marker_behind(self):
        store, wt, item, step = _world()
        _complete(store, wt, step)
        self.assertNotIn(RELEASE_PENDING_LABEL, store.labels_of(item))


def _shift(ts, micros):
    return (datetime.datetime.fromisoformat(ts) + datetime.timedelta(microseconds=micros)).isoformat()


if __name__ == "__main__":
    unittest.main()
