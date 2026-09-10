import json
import unittest

from lightcycle.application.feedback.retro import RetroInput, RetroUseCase
from lightcycle.application.pool.retro_cadence import RetroCadenceUseCase
from lightcycle.application.services.flow import FlowService
from lightcycle.application.work.pending_reflections import pending_reflection_count
from lightcycle.domain.work import NodeQueue, State, node_id_key
from tests.support.fake_fs import FakeFs
from tests.support.fake_store import FakeStore
from tests.support.factories import make_step


def _flow(store):
    return FlowService(FakeFs({}), store)


class FakeConfig:
    def __init__(self, interval_reflections=3):
        self._interval = interval_reflections

    def retro_interval_reflections(self):
        return self._interval


def _add_reflection(store, node_id, feedback):
    store.add_artifact(
        node_id, "reflection", json.dumps({"step": node_id, "feedback": feedback, "spec_hash": "h"})
    )


def _close_item(store, title, repo=None, reflections=0, id=None):
    eid = store.create_item(title, "a description", id=id)
    store.complete_node(eid, "done")
    if repo is not None:
        store.add_artifact(eid, "repo", repo)
    if reflections:
        k = store.create_step("build: x", step="build", role="agent", parent=eid)
        store.complete_node(k, "done")
        for i in range(reflections):
            _add_reflection(store, k, "fb %d" % i)
    return eid


def _open_item_with_closed_pass(store, title, reflections=0):
    eid = store.create_item(title, "a description")
    pid = store.open_pass(eid)
    if reflections:
        k = store.create_step("build: x", step="build", role="agent", parent=eid)
        store.set_step_pass(k, pid)
        store.complete_node(k, "done")
        for i in range(reflections):
            _add_reflection(store, k, "fb %d" % i)
    store.close_pass(pid)
    return eid, pid


def _gate(store, interval_reflections=3):
    return RetroCadenceUseCase(store, FakeConfig(interval_reflections))


class TestRetroCadenceNoFire(unittest.TestCase):
    def test_no_closed_items_does_not_fire(self):
        s = FakeStore()
        self.assertEqual(_gate(s).execute(0.0).fired, [])

    def test_below_threshold_does_not_fire(self):
        s = FakeStore()
        for i in range(2):
            _close_item(s, "item %d" % i, reflections=1)
        self.assertEqual(_gate(s, interval_reflections=3).execute(0.0).fired, [])


class TestRetroCadenceFires(unittest.TestCase):
    def test_threshold_fires_one_global_audit(self):
        s = FakeStore()
        for i in range(3):
            _close_item(s, "item %d" % i, reflections=1)
        result = _gate(s, interval_reflections=3).execute(0.0)
        self.assertEqual(len(result.fired), 1)

    def test_fires_the_fixed_engine_audit_stage_owned_by_the_agent_role(self):
        s = FakeStore()
        for i in range(3):
            _close_item(s, "item %d" % i, reflections=1)
        step = s.get_node(_gate(s, interval_reflections=3).execute(0.0).fired[0])
        self.assertEqual(step.step, "audit")
        self.assertEqual(step.role, "agent")

    def test_fired_audit_has_a_real_item_parent_carrying_retro_origin_and_no_repo(self):
        s = FakeStore()
        for i in range(3):
            _close_item(s, "item %d" % i, reflections=1)
        result = _gate(s, interval_reflections=3).execute(0.0)
        step = s.get_node(result.fired[0])
        self.assertIsNotNone(step.parent)
        parent = s.get_node(step.parent)
        self.assertEqual(parent.type, "item")
        self.assertEqual(s.item_artifacts(parent.id), [])
        s.complete_node(step.parent, "done")
        self.assertNotIn(step.parent, [i.id for i in s.closed_unretroed_items()])

    def test_fired_audit_title(self):
        s = FakeStore()
        for i in range(3):
            _close_item(s, "item %d" % i, reflections=1)
        step = s.get_node(_gate(s, interval_reflections=3).execute(0.0).fired[0])
        self.assertEqual(step.title, "audit: Audit of 3 closed items, 0 closed passes")

    def test_items_without_feedback_do_not_count(self):
        s = FakeStore()
        for i in range(3):
            _close_item(s, "item %d" % i)
        self.assertEqual(_gate(s, interval_reflections=3).execute(0.0).fired, [])

    def test_item_with_repo_but_no_reflection_does_not_count(self):
        s = FakeStore()
        for i in range(3):
            _close_item(s, "item %d" % i, repo="lightcycle")
        self.assertEqual(_gate(s, interval_reflections=3).execute(0.0).fired, [])

    def test_item_without_repo_but_with_reflection_counts(self):
        s = FakeStore()
        for i in range(3):
            _close_item(s, "item %d" % i, reflections=1)
        self.assertEqual(len(_gate(s, interval_reflections=3).execute(0.0).fired), 1)

    def test_single_global_audit_fires_across_several_distinct_repos_plus_projectless(self):
        s = FakeStore()
        _close_item(s, "lc", repo="lightcycle", reflections=1)
        _close_item(s, "saga", repo="saga", reflections=1)
        _close_item(s, "orphan", reflections=1)
        self.assertEqual(len(_gate(s, interval_reflections=3).execute(0.0).fired), 1)

    def test_counts_reflections_not_items_regardless_of_distribution(self):
        s = FakeStore()
        _close_item(s, "thin", reflections=1)
        _close_item(s, "thick", reflections=2)
        self.assertEqual(len(_gate(s, interval_reflections=3).execute(0.0).fired), 1)

    def test_fired_audit_parent_item_reads_queued_not_backlogged(self):
        s = FakeStore()
        for i in range(3):
            _close_item(s, "item %d" % i, reflections=1)
        step = s.get_node(_gate(s, interval_reflections=3).execute(0.0).fired[0])
        parent = s.get_node(step.parent)
        self.assertEqual(parent.state, State.QUEUED)

    def test_fired_audit_title_and_description_count_only_the_feedback_carrying_batch(self):
        s = FakeStore()
        feedback_ids = [_close_item(s, "item %d" % i, reflections=1) for i in range(3)]
        no_feedback_id = _close_item(s, "no feedback item")
        step = s.get_node(_gate(s, interval_reflections=3).execute(0.0).fired[0])
        parent = s.get_node(step.parent)
        self.assertEqual(parent.title, "Audit of 3 closed items, 0 closed passes")
        self.assertEqual(
            parent.description,
            "batch: %s" % ", ".join(sorted(feedback_ids, key=node_id_key)),
        )
        self.assertNotIn(no_feedback_id, parent.description)

    def test_fired_audit_description_orders_ids_numerically_not_by_string(self):
        s = FakeStore()
        _close_item(s, "ten", reflections=1, id="proj-10")
        _close_item(s, "nine", reflections=1, id="proj-9")
        step = s.get_node(_gate(s, interval_reflections=2).execute(0.0).fired[0])
        parent = s.get_node(step.parent)
        self.assertEqual(parent.description, "batch: proj-9, proj-10")

    def test_parent_item_reads_running_once_audit_is_claimed(self):
        s = FakeStore()
        for i in range(3):
            _close_item(s, "item %d" % i, reflections=1)
        step = s.get_node(_gate(s, interval_reflections=3).execute(0.0).fired[0])
        s.assign(step.id, "audit")
        s.update_state(step.id, State.RUNNING)
        parent = s.get_node(step.parent)
        self.assertEqual(parent.state, State.RUNNING)


class TestRetroCadenceNoRunaway(unittest.TestCase):
    def test_does_not_refire_while_an_audit_is_open(self):
        s = FakeStore()
        for i in range(3):
            _close_item(s, "item %d" % i, reflections=1)
        gate = _gate(s, interval_reflections=3)
        self.assertEqual(len(gate.execute(0.0).fired), 1)
        self.assertEqual(gate.execute(0.0).fired, [])

    def test_marked_batch_does_not_refire_after_audit_closes(self):
        s = FakeStore()
        items = [_close_item(s, "item %d" % i, reflections=1) for i in range(3)]
        gate = _gate(s, interval_reflections=3)
        first = gate.execute(0.0)
        for item in items:
            s.label_add(item, "retroed")
        s.complete_node(first.fired[0], "clean")
        self.assertEqual(gate.execute(0.0).fired, [])

    def test_refires_for_a_fresh_batch(self):
        s = FakeStore()
        items = [_close_item(s, "item %d" % i, reflections=1) for i in range(3)]
        gate = _gate(s, interval_reflections=3)
        first = gate.execute(0.0)
        for item in items:
            s.label_add(item, "retroed")
        s.complete_node(first.fired[0], "clean")
        for i in range(3):
            _close_item(s, "fresh %d" % i, reflections=1)
        self.assertEqual(len(gate.execute(0.0).fired), 1)


class TestRetroCadenceExcludes(unittest.TestCase):
    def test_retro_origin_item_excluded(self):
        s = FakeStore()
        for i in range(2):
            _close_item(s, "real %d" % i, reflections=1)
        s.label_add(_close_item(s, "retro origin", reflections=1), "retro-origin")
        self.assertEqual(_gate(s, interval_reflections=3).execute(0.0).fired, [])

    def test_retroed_item_excluded(self):
        s = FakeStore()
        for i in range(2):
            _close_item(s, "real %d" % i, reflections=1)
        s.label_add(_close_item(s, "already retroed", reflections=1), "retroed")
        self.assertEqual(_gate(s, interval_reflections=3).execute(0.0).fired, [])


class TestRetroCadenceFiresForOpenItemPasses(unittest.TestCase):
    def test_reflections_on_closed_passes_of_items_that_never_close_still_fire(self):
        s = FakeStore()
        for i in range(3):
            _open_item_with_closed_pass(s, "loop %d" % i, reflections=1)
        result = _gate(s, interval_reflections=3).execute(0.0)
        self.assertEqual(len(result.fired), 1)

    def test_mixed_batch_of_closed_items_and_closed_passes_fires_exactly_one_audit(self):
        s = FakeStore()
        _close_item(s, "closed item", reflections=2)
        _open_item_with_closed_pass(s, "looping item", reflections=1)
        result = _gate(s, interval_reflections=3).execute(0.0)
        self.assertEqual(len(result.fired), 1)

    def test_fired_audit_description_names_both_item_and_pass_ids(self):
        s = FakeStore()
        item_id = _close_item(s, "closed item", reflections=2)
        looping_item, pid = _open_item_with_closed_pass(s, "looping item", reflections=1)
        step = s.get_node(_gate(s, interval_reflections=3).execute(0.0).fired[0])
        parent = s.get_node(step.parent)
        self.assertEqual(parent.title, "Audit of 1 closed items, 1 closed passes")
        self.assertEqual(
            parent.description, "batch: %s" % ", ".join(sorted([item_id, pid]))
        )


class TestRetroCadenceNoRunawayForPasses(unittest.TestCase):
    def test_does_not_refire_while_an_audit_is_open(self):
        s = FakeStore()
        for i in range(3):
            _open_item_with_closed_pass(s, "loop %d" % i, reflections=1)
        gate = _gate(s, interval_reflections=3)
        self.assertEqual(len(gate.execute(0.0).fired), 1)
        self.assertEqual(gate.execute(0.0).fired, [])

    def test_manually_retroed_pass_does_not_cause_refire(self):
        s = FakeStore()
        _, pid = _open_item_with_closed_pass(s, "loop", reflections=3)
        s.label_add(pid, "retroed")
        self.assertEqual(_gate(s, interval_reflections=3).execute(0.0).fired, [])

    def test_fresh_pass_on_a_different_still_open_item_does_refire(self):
        s = FakeStore()
        _, pid = _open_item_with_closed_pass(s, "loop", reflections=3)
        s.label_add(pid, "retroed")
        gate = _gate(s, interval_reflections=3)
        self.assertEqual(gate.execute(0.0).fired, [])
        _open_item_with_closed_pass(s, "fresh loop", reflections=3)
        self.assertEqual(len(gate.execute(0.0).fired), 1)


class TestRetroCadenceExcludesPasses(unittest.TestCase):
    def test_retro_origin_pass_excluded(self):
        s = FakeStore()
        for i in range(2):
            _close_item(s, "real %d" % i, reflections=1)
        _, pid = _open_item_with_closed_pass(s, "retro origin loop", reflections=1)
        s.label_add(pid, "retro-origin")
        self.assertEqual(_gate(s, interval_reflections=3).execute(0.0).fired, [])

    def test_retroed_pass_excluded(self):
        s = FakeStore()
        for i in range(2):
            _close_item(s, "real %d" % i, reflections=1)
        _, pid = _open_item_with_closed_pass(s, "already retroed loop", reflections=1)
        s.label_add(pid, "retroed")
        self.assertEqual(_gate(s, interval_reflections=3).execute(0.0).fired, [])


class TestCadenceAndPendingHeaderAgree(unittest.TestCase):
    def test_cadence_trigger_count_matches_pending_header_count(self):
        s = FakeStore()
        _close_item(s, "thin", reflections=1)
        _close_item(s, "thick", reflections=4)
        _close_item(s, "no feedback", reflections=0)
        cadence_count = pending_reflection_count(s)
        pending_resp = RetroUseCase(s, _flow(s)).execute(RetroInput(pending=True))
        self.assertEqual(cadence_count, pending_resp.reflection_count)


class TestRetroCadenceAtomicity(unittest.TestCase):
    def test_a_failing_create_step_leaves_the_audit_item_and_label_unapplied(self):
        s = FakeStore()
        for i in range(3):
            _close_item(s, "item %d" % i, reflections=1)
        before_ids = {i.id for i in s.all_items()}

        def raising_create_step(*args, **kwargs):
            raise RuntimeError("boom")

        s.create_step = raising_create_step
        gate = _gate(s, interval_reflections=3)
        with self.assertRaises(RuntimeError):
            gate.execute(0.0)
        self.assertEqual({i.id for i in s.all_items()}, before_ids)


class TestRetroLaneVisibility(unittest.TestCase):
    def test_queued_audit_is_in_queue(self):
        q = NodeQueue([make_step(id="a", state=State.QUEUED, role="agent", step="audit")])
        self.assertEqual([t.id for t in q.by_lane()["queue"]], ["a"])

    def test_running_audit_is_active(self):
        q = NodeQueue([make_step(id="a", state=State.RUNNING, role="agent", step="audit")])
        self.assertEqual([t.id for t in q.by_lane()["active"]], ["a"])


if __name__ == "__main__":
    unittest.main()
