import unittest

from lightcycle.application.work.hierarchy import HierarchyInput, HierarchyUseCase
from lightcycle.domain.runs import pass_number
from lightcycle.domain.work import row_bucket
from lightcycle.domain.work.callout_runs import CALLOUT_RUNS, dump_runs
from lightcycle.domain.work.item import Item
from lightcycle.domain.work.step import Step
from tests.support.fake_fs import flow_from_metas
from tests.support.fake_store import FakeStore
from tests.support.step_factory import create_owned_step

FLOW = flow_from_metas(
    {"coder": {"model": "sonnet", "step": "build", "routes": {"done": "review"}}}
)


class TestHierarchyUseCase(unittest.TestCase):
    def test_opening_from_a_step_roots_at_its_item(self):
        s = FakeStore()
        item = s.create_item("item", "a description")
        step = s.create_step(stage="write-code", role="agent", item=item)
        rows = HierarchyUseCase(s).execute(HierarchyInput(node=step)).rows
        self.assertEqual([(r.node.id, r.depth) for r in rows], [(item, 0), (step, 1)])

    def test_a_repeated_stage_counts_its_rounds_in_order(self):
        s = FakeStore()
        item = s.create_item("item", "a description")
        code1 = s.create_step(stage="write-code", role="agent", item=item)
        review1 = s.create_step(stage="review-code", role="agent", item=item)
        code2 = s.create_step(stage="write-code", role="agent", item=item)
        rows = HierarchyUseCase(s).execute(HierarchyInput(node=item)).rows
        self.assertEqual(
            [(r.node.id, r.round) for r in rows],
            [(item, 1), (code1, 1), (review1, 1), (code2, 2)],
        )

    def test_an_items_siblings_are_not_shown(self):
        s = FakeStore()
        other = s.create_item("other", "a description")
        item = s.create_item("item", "a description")
        step = s.create_step(stage="write-code", role="agent", item=item)
        rows = HierarchyUseCase(s).execute(HierarchyInput(node=item)).rows
        self.assertEqual([r.node.id for r in rows], [item, step])
        self.assertNotIn(other, [r.node.id for r in rows])

    def test_an_item_is_its_own_root(self):
        s = FakeStore()
        item = s.create_item("solo", "a description")
        step = s.create_step(stage="write-code", role="agent", item=item)
        rows = HierarchyUseCase(s).execute(HierarchyInput(node=item)).rows
        self.assertEqual([(r.node.id, r.depth) for r in rows], [(item, 0), (step, 1)])

    def test_backlog_item_with_no_steps_shows_only_itself(self):
        s = FakeStore()
        item = s.create_item("solo", "a description")
        rows = HierarchyUseCase(s).execute(HierarchyInput(node=item)).rows
        self.assertEqual([r.node.id for r in rows], [item])

    def test_steps_enrolled_into_a_real_pass_still_render_flat_at_depth_one(self):
        s = FakeStore()
        item = s.create_item("item", "a description")
        pid1 = s.open_pass(item)
        step1 = s.create_step(stage="build", role="agent", item=item)
        s.set_step_pass(step1, pid1)
        s.close_pass(pid1)
        pid2 = s.open_pass(item)
        step2 = s.create_step(stage="build", role="agent", item=item)
        s.set_step_pass(step2, pid2)
        rows = HierarchyUseCase(s).execute(HierarchyInput(node=item)).rows
        self.assertEqual([(r.node.id, r.depth) for r in rows], [
            (item, 0), (step1, 1), (step2, 1),
        ])
        self.assertTrue(all(r.depth != 2 for r in rows))
        self.assertTrue(all(isinstance(r.node, (Item, Step)) for r in rows))

    def test_multi_pass_is_false_for_a_single_pass_item(self):
        s = FakeStore()
        item = s.create_item("item", "a description")
        pid = s.open_pass(item)
        step = s.create_step(stage="build", role="agent", item=item)
        s.set_step_pass(step, pid)
        response = HierarchyUseCase(s).execute(HierarchyInput(node=item))
        self.assertFalse(response.multi_pass)

    def test_multi_pass_is_true_once_a_second_pass_opens_even_before_it_has_any_steps(self):
        s = FakeStore()
        item = s.create_item("item", "a description")
        pid1 = s.open_pass(item)
        step1 = s.create_step(stage="build", role="agent", item=item)
        s.set_step_pass(step1, pid1)
        s.close_pass(pid1)
        s.open_pass(item)
        response = HierarchyUseCase(s).execute(HierarchyInput(node=item))
        self.assertTrue(response.multi_pass)

    def test_multi_pass_stays_true_once_every_pass_has_since_closed(self):
        s = FakeStore()
        item = s.create_item("item", "a description")
        pid1 = s.open_pass(item)
        step1 = s.create_step(stage="build", role="agent", item=item)
        s.set_step_pass(step1, pid1)
        s.close_pass(pid1)
        pid2 = s.open_pass(item)
        step2 = s.create_step(stage="build", role="agent", item=item)
        s.set_step_pass(step2, pid2)
        s.close_pass(pid2)
        response = HierarchyUseCase(s).execute(HierarchyInput(node=item))
        self.assertTrue(response.multi_pass)


class TestPassNumber(unittest.TestCase):
    def test_none_is_pass_one(self):
        self.assertEqual(pass_number(None), 1)

    def test_first_pass_id_is_one(self):
        self.assertEqual(pass_number("LC-1.p1"), 1)

    def test_second_pass_id_is_two(self):
        self.assertEqual(pass_number("LC-1.p2"), 2)


class TestRowBucket(unittest.TestCase):
    def test_dependency_blocked_step_is_queued(self):
        s = FakeStore()
        blocker = create_owned_step(s, "b", stage="build", role="agent")
        step = create_owned_step(s, "s", stage="build", role="agent", deps=[blocker])
        self.assertEqual(row_bucket(s.get_node(step), FLOW, True), "queued")

    def test_human_ready_step_unknown_to_the_flow_is_a_gate(self):
        s = FakeStore()
        step = create_owned_step(s, "s", stage="await-merge", role="human")
        self.assertEqual(row_bucket(s.get_node(step), FLOW, True), "gate")

    def test_a_parked_step_the_flow_still_owns_by_an_agent_is_an_escalation(self):
        s = FakeStore()
        step = create_owned_step(s, "s", stage="build", role="human")
        self.assertEqual(row_bucket(s.get_node(step), FLOW, True), "escalation")

    def test_queued_agent_step_is_queued(self):
        s = FakeStore()
        step = create_owned_step(s, "s", stage="build", role="agent")
        self.assertEqual(row_bucket(s.get_node(step), FLOW, True), "queued")

    def test_in_progress_step_is_active(self):
        s = FakeStore()
        step = create_owned_step(s, "s", stage="build", role="agent")
        s.claim_ready("agent")
        self.assertEqual(row_bucket(s.get_node(step), FLOW, True), "active")

    def test_done_step_is_done(self):
        s = FakeStore()
        step = create_owned_step(s, "s", stage="build", role="agent")
        s.complete_node(step, "done")
        self.assertEqual(row_bucket(s.get_node(step), FLOW, True), "done")

    def test_dependency_blocked_item_is_queued(self):
        s = FakeStore()
        blocker = s.create_item("blocker", "a description")
        item = s.create_item("blocked", "a description")
        s.dep_add(item, blocker)
        self.assertEqual(row_bucket(s.get_node(item), FLOW, True), "queued")

    def test_a_ready_step_with_no_recorded_role_is_treated_as_human(self):
        s = FakeStore()
        step = create_owned_step(s, "s", stage="await-merge")
        self.assertEqual(row_bucket(s.get_node(step), FLOW, True), "gate")

    def test_item_with_a_human_step_awaiting_it_alongside_done_steps_is_a_gate(self):
        s = FakeStore()
        item = s.create_item("item", "a description")
        for i in range(11):
            done = s.create_step(stage="build", role="agent", item=item)
            s.complete_node(done, "done")
        s.create_step(stage="await-merge", role="human", item=item)
        self.assertEqual(row_bucket(s.get_node(item), FLOW, True), "gate")

    def test_unblocked_engine_step_is_active(self):
        s = FakeStore()
        step = create_owned_step(s, "s", stage="poll-ci", role="engine")
        self.assertEqual(row_bucket(s.get_node(step), FLOW, True), "active")

    def test_unblocked_engine_step_is_queued_while_the_pool_is_stopped(self):
        s = FakeStore()
        step = create_owned_step(s, "s", stage="poll-ci", role="engine")
        self.assertEqual(row_bucket(s.get_node(step), FLOW, False), "queued")

    def test_running_agent_step_is_active_while_the_pool_is_stopped(self):
        s = FakeStore()
        step = create_owned_step(s, "s", stage="build", role="agent")
        s.claim_ready("agent")
        self.assertEqual(row_bucket(s.get_node(step), FLOW, False), "active")

    def test_human_gate_is_unaffected_by_the_pool_being_stopped(self):
        s = FakeStore()
        step = create_owned_step(s, "s", stage="await-merge", role="human")
        self.assertEqual(row_bucket(s.get_node(step), FLOW, False), "gate")

    def test_dependency_blocked_engine_step_is_queued(self):
        s = FakeStore()
        blocker = create_owned_step(s, "b", stage="build", role="agent")
        step = create_owned_step(s, "s", stage="poll-ci", role="engine", deps=[blocker])
        self.assertEqual(row_bucket(s.get_node(step), FLOW, True), "queued")

    def test_queued_item_whose_only_child_is_an_engine_step_does_not_raise(self):
        s = FakeStore()
        item = s.create_item("item", "a description")
        s.create_step(stage="poll-ci", role="engine", item=item)
        self.assertEqual(row_bucket(s.get_node(item), FLOW, True), "queued")


def _record(status, wait=False, started=0, finished=None, artifacts=None):
    record = {"status": status, "wait": wait, "started": started, "artifacts": artifacts or []}
    if finished is not None:
        record["finished"] = finished
    return record


def _runs(store, step, runs):
    store.replace_artifact(step, CALLOUT_RUNS, dump_runs(runs), internal=True)


class TestCalloutRows(unittest.TestCase):
    def test_a_step_with_two_records_yields_two_rows_after_it_in_record_order(self):
        s = FakeStore()
        item = s.create_item("item", "a description")
        step = s.create_step(stage="write-code", role="human", item=item)
        _runs(s, step, {"b": _record("ok", finished=5), "a": _record("running", wait=True)})

        rows = HierarchyUseCase(s).execute(HierarchyInput(node=item)).rows

        self.assertEqual([r.node.id for r in rows], [item, step, step, step])
        self.assertEqual([r.depth for r in rows], [0, 1, 2, 2])
        self.assertEqual([r.callout for r in rows[:2]], [None, None])
        self.assertEqual([r.callout.callout_id for r in rows[2:]], ["b", "a"])
        self.assertEqual(rows[2].callout.status, "ok")
        self.assertEqual(rows[2].callout.finished, 5)
        self.assertTrue(rows[3].callout.wait)

    def test_a_step_with_no_artifact_yields_no_callout_rows(self):
        s = FakeStore()
        item = s.create_item("item", "a description")
        step = s.create_step(stage="write-code", role="human", item=item)

        rows = HierarchyUseCase(s).execute(HierarchyInput(node=item)).rows

        self.assertEqual([r.node.id for r in rows], [item, step])
        self.assertTrue(all(r.callout is None for r in rows))

    def test_a_non_dict_record_is_dropped(self):
        s = FakeStore()
        item = s.create_item("item", "a description")
        step = s.create_step(stage="write-code", role="human", item=item)
        _runs(s, step, {"junk": "oops", "a": _record("ok", finished=1)})

        rows = HierarchyUseCase(s).execute(HierarchyInput(node=item)).rows

        self.assertEqual([r.callout.callout_id for r in rows if r.callout], ["a"])

    def test_mixed_statuses_list_under_their_gate_only_with_distinct_keys(self):
        s = FakeStore()
        item = s.create_item("item", "a description")
        first = s.create_step(stage="write-code", role="human", item=item)
        second = s.create_step(stage="review", role="human", item=item)
        _runs(s, first, {
            "x": _record("ok", finished=2), "y": _record("failed", finished=3),
            "z": _record("running")})

        rows = HierarchyUseCase(s).execute(HierarchyInput(node=item)).rows

        self.assertEqual(rows[1].node.id, first)
        self.assertEqual([r.node.id for r in rows], [item, first, first, first, first, second])
        self.assertEqual([r.callout.status for r in rows[2:5]], ["ok", "failed", "running"])
        keys = [r.row_key for r in rows]
        self.assertEqual(len(set(keys)), len(keys))
        self.assertEqual(rows[2].row_key, "callout:%s:x" % first)
        self.assertEqual(rows[1].row_key, first)
