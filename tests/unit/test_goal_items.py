import unittest

from lightcycle.adapters.tui.priority_list import (
    assemble_rows,
    build_priority_rows_from_selection,
)
from lightcycle.application.errors import UseCaseError
from lightcycle.application.goals import GoalItemsUseCase
from lightcycle.application.work.item_partition import is_backlogged_item, is_closed_item
from lightcycle.application.work.priority_rows import select_priority_rows
from lightcycle.application.work.status import StatusUseCase
from lightcycle.application.work.suspended_steps import suspended_step_ids
from lightcycle.domain.work import State
from lightcycle.ports.workers import RegistryUnreadable
from tests.support.fake_fs import flow_from_metas
from tests.support.fake_store import FakeStore
from tests.support.fake_workers import FakeWorkers

_FLOW = flow_from_metas(
    {
        "coder": {"model": "sonnet", "step": "build", "routes": {"done": "review"}},
        "ready-merge": {"step": "ready-merge", "routes": {"merged": "cleanup", "changes": "build"}},
    }
)


class FixedFlowService:
    def flow_for(self, node):
        return _FLOW


class UnreadableWorkers(FakeWorkers):
    def workers_state(self):
        raise RegistryUnreadable("gone")


class GoalItemsFixture(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        self.goal = self.store.create_goal("g", "d", "acme")
        self.flow = FixedFlowService()

    def _link(self, item):
        self.store.link_goal_item(self.goal, item)
        return item

    def backlogged(self, title="backlogged"):
        return self._link(self.store.create_item(title, "d"))

    def closed(self, title="closed"):
        item = self._link(self.store.create_item(title, "d"))
        self.store.complete_node(item, "merged")
        return item

    def with_step(self, title, role="agent", deps=None, running=False):
        item = self._link(self.store.create_item(title, "d"))
        step = self.store.create_step(step="build", role=role, parent=item, deps=deps)
        if running:
            self.store.assign(step, "worker-1")
            self.store.update_state(step, State.RUNNING)
        return item, step

    def execute(self, text=None):
        return GoalItemsUseCase(self.store, self.flow).execute(self.goal, text)

    def selected_ids(self, result):
        rows = result.selection.attention + result.selection.active + result.selection.queued
        return [r.owning_node.id for r in rows]


class TestGoalItemsUseCase(GoalItemsFixture):
    def test_each_item_lands_in_exactly_one_group_in_the_lane_order(self):
        backlogged = self.backlogged()
        done = self.closed()
        gate, _ = self.with_step("gate", role="human")
        active, active_step = self.with_step("active", running=True)
        queued, _ = self.with_step("queued")
        held, _ = self.with_step("held", deps=[active_step])

        result = self.execute()

        self.assertEqual(self.selected_ids(result), [gate, active, queued, held])
        self.assertEqual([r.id for r in result.backlog], [backlogged])
        self.assertEqual([r.id for r in result.done], [done])
        self.assertEqual(result.stepless, [])
        self.assertEqual(result.total, 6)

    def test_current_work_membership_is_the_selection_current_work_uses(self):
        self.with_step("gate", role="human")
        self.with_step("queued")
        result = self.execute()
        lanes = StatusUseCase(self.store).execute().lanes
        expected = select_priority_rows(self.store, lanes, self.flow)
        self.assertEqual(result.selection, expected)

    def test_open_item_in_no_lane_is_current_work_without_a_step(self):
        watcher, _ = self.with_step("watcher")
        item = self._link(self.store.create_item("watched only", "d"))
        watched = self.store.create_step(step="build", role="agent", parent=item)
        self.store.set_watched_step(self.store.create_step(step="build", role="agent", parent=watcher), watched)

        result = self.execute()

        self.assertEqual([r.id for r in result.stepless], [item])
        self.assertNotIn(item, [r.id for r in result.backlog + result.done])

    def test_a_link_to_a_missing_node_is_done_with_no_title(self):
        self.store.link_goal_item(self.goal, "LC-404")
        result = self.execute()
        self.assertEqual([(r.id, r.title) for r in result.done], [("LC-404", None)])

    def test_items_outside_the_goal_are_left_out(self):
        self.backlogged()
        other = self.store.create_item("elsewhere", "d")
        self.store.create_step(step="build", role="agent", parent=other)
        result = self.execute()
        self.assertEqual(self.selected_ids(result), [])
        self.assertEqual(len(result.backlog), 1)

    def test_filter_narrows_every_group_and_total_counts_all_linked(self):
        self.backlogged("alpha backlog")
        self.backlogged("beta backlog")
        self.closed("alpha done")
        self.closed("beta done")
        alpha, _ = self.with_step("alpha queued")
        self.with_step("beta queued")
        self.store.link_goal_item(self.goal, "LC-404")

        result = self.execute("ALPHA")

        self.assertEqual([r.title for r in result.backlog], ["alpha backlog"])
        self.assertEqual([r.title for r in result.done], ["alpha done"])
        self.assertEqual(self.selected_ids(result), [alpha])
        self.assertEqual(result.total, 7)

    def test_filter_matching_everything_and_nothing(self):
        self.backlogged()
        self.with_step("queued")
        everything = self.execute("")
        self.assertEqual(len(everything.backlog), 1)
        self.assertEqual(len(self.selected_ids(everything)), 1)
        nothing = self.execute("zzz")
        self.assertEqual(nothing.backlog, [])
        self.assertEqual(self.selected_ids(nothing), [])
        self.assertEqual(nothing.total, 2)

    def test_a_missing_node_is_filtered_by_its_id(self):
        self.store.link_goal_item(self.goal, "LC-404")
        self.assertEqual(self.execute("nomatch").done, [])
        self.assertEqual(len(self.execute("404").done), 1)

    def test_unknown_goal_refuses(self):
        with self.assertRaises(UseCaseError):
            GoalItemsUseCase(self.store, self.flow).execute("G-999")

    def test_rows_agree_with_current_work_for_the_same_items(self):
        _, gate_step = self.with_step("gate", role="human")
        _, active_step = self.with_step("active", running=True)
        self.with_step("queued")
        self.with_step("held", deps=[active_step])
        suspended = frozenset({active_step})

        result = self.execute()
        goal_rows = assemble_rows(*build_priority_rows_from_selection(self.store, result.selection, suspended))
        lanes = StatusUseCase(self.store).execute().lanes
        lane_rows = assemble_rows(
            *build_priority_rows_from_selection(
                self.store, select_priority_rows(self.store, lanes, self.flow), suspended
            )
        )

        self.assertEqual(goal_rows, lane_rows)
        self.assertTrue(any(r.suspended for r in goal_rows))
        self.assertTrue(any(r.dependency_icon for r in goal_rows))


class TestSharedPredicates(GoalItemsFixture):
    def test_is_backlogged_item(self):
        backlogged = self.store.get_node(self.backlogged())
        running, _ = self.with_step("running", running=True)
        self.assertTrue(is_backlogged_item(self.store, backlogged))
        self.assertFalse(is_backlogged_item(self.store, self.store.get_node(running)))

    def test_is_backlogged_item_blocked_with_no_children_is_true_and_with_children_false(self):
        blocker = self.store.create_item("blocker", "d")
        bare = self.store.create_item("bare", "d")
        self.store.dep_add(bare, blocker)
        with_child = self.store.create_item("with child", "d")
        self.store.create_step(step="build", role="agent", parent=with_child)
        self.store.dep_add(with_child, blocker)

        self.assertEqual(self.store.get_node(bare).state, State.BLOCKED)
        self.assertTrue(is_backlogged_item(self.store, self.store.get_node(bare)))
        self.assertEqual(self.store.get_node(with_child).state, State.BLOCKED)
        self.assertFalse(is_backlogged_item(self.store, self.store.get_node(with_child)))

    def test_is_closed_item(self):
        closed = self.store.get_node(self.closed())
        open_item = self.store.get_node(self.backlogged())
        self.assertTrue(is_closed_item(closed))
        self.assertFalse(is_closed_item(open_item))


class TestSuspendedStepIds(unittest.TestCase):
    def test_returns_the_steps_of_suspended_workers_only(self):
        workers = FakeWorkers(
            workers=[
                {"spawnid": "a", "pid": 1, "step": "S-1", "started": 0, "suspended": True, "suspended_at": 0},
                {"spawnid": "b", "pid": 2, "step": "S-2", "started": 0},
                {"spawnid": "c", "pid": 3, "started": 0, "suspended": True, "suspended_at": 0},
            ],
            alive_pids=(1, 2, 3),
        )
        self.assertEqual(suspended_step_ids(workers), frozenset({"S-1"}))

    def test_a_dead_suspended_worker_does_not_suspend_a_step_a_live_worker_holds(self):
        workers = FakeWorkers(
            workers=[
                {"spawnid": "dead", "pid": 1, "step": "S-1", "started": 0, "suspended": True, "suspended_at": 0},
                {"spawnid": "live", "pid": 2, "step": "S-1", "started": 0},
            ],
            alive_pids=(2,),
        )
        self.assertEqual(suspended_step_ids(workers), frozenset())

    def test_a_dead_suspended_worker_alone_suspends_nothing(self):
        workers = FakeWorkers(
            workers=[{"spawnid": "dead", "pid": 1, "step": "S-1", "started": 0, "suspended": True, "suspended_at": 0}],
        )
        self.assertEqual(suspended_step_ids(workers), frozenset())

    def test_an_unreadable_registry_yields_the_empty_set(self):
        self.assertEqual(suspended_step_ids(UnreadableWorkers()), frozenset())
