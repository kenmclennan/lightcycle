import json
import unittest

from lightcycle.application.feedback.retro import RetroInput, RetroUseCase
from lightcycle.application.pool.retro_cadence import RetroCadenceUseCase
from lightcycle.application.services.flow import FlowService
from lightcycle.application.work.pending_reflections import pending_reflection_count
from lightcycle.domain.work import Node, NodeQueue, State
from tests.support.fake_fs import FakeFs
from tests.support.fake_store import FakeStore


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


def _close_item(store, title, repo=None, reflections=0):
    eid = store.create_item(title)
    store.close(eid, "done")
    if repo is not None:
        store.add_artifact(eid, "repo", repo)
    if reflections:
        k = store.create_step("build: x", step="build", role="coder", parent=eid)
        store.close(k, "done")
        for i in range(reflections):
            _add_reflection(store, k, "fb %d" % i)
    return eid


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

    def test_fires_the_fixed_engine_audit_step_and_role(self):
        s = FakeStore()
        for i in range(3):
            _close_item(s, "item %d" % i, reflections=1)
        step = s.get_node(_gate(s, interval_reflections=3).execute(0.0).fired[0])
        self.assertEqual(step.step, "audit")
        self.assertEqual(step.role, "audit")

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
        s.close(step.parent, "done")
        self.assertNotIn(step.parent, [i.id for i in s.closed_unretroed_items()])

    def test_fired_audit_title(self):
        s = FakeStore()
        for i in range(3):
            _close_item(s, "item %d" % i, reflections=1)
        step = s.get_node(_gate(s, interval_reflections=3).execute(0.0).fired[0])
        self.assertEqual(step.title, "audit: pending-feedback")

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

    def test_fired_audit_parent_item_reads_ready_not_backlogged(self):
        s = FakeStore()
        for i in range(3):
            _close_item(s, "item %d" % i, reflections=1)
        step = s.get_node(_gate(s, interval_reflections=3).execute(0.0).fired[0])
        parent = s.get_node(step.parent)
        self.assertEqual(parent.state, State.READY)

    def test_parent_item_reads_in_progress_once_audit_is_claimed(self):
        s = FakeStore()
        for i in range(3):
            _close_item(s, "item %d" % i, reflections=1)
        step = s.get_node(_gate(s, interval_reflections=3).execute(0.0).fired[0])
        s.assign(step.id, "audit")
        s.update_state(step.id, State.IN_PROGRESS)
        parent = s.get_node(step.parent)
        self.assertEqual(parent.state, State.IN_PROGRESS)


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
        s.close(first.fired[0], "clean")
        self.assertEqual(gate.execute(0.0).fired, [])

    def test_refires_for_a_fresh_batch(self):
        s = FakeStore()
        items = [_close_item(s, "item %d" % i, reflections=1) for i in range(3)]
        gate = _gate(s, interval_reflections=3)
        first = gate.execute(0.0)
        for item in items:
            s.label_add(item, "retroed")
        s.close(first.fired[0], "clean")
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


class TestCadenceAndPendingHeaderAgree(unittest.TestCase):
    def test_cadence_trigger_count_matches_pending_header_count(self):
        s = FakeStore()
        _close_item(s, "thin", reflections=1)
        _close_item(s, "thick", reflections=4)
        _close_item(s, "no feedback", reflections=0)
        cadence_count = pending_reflection_count(s)
        pending_resp = RetroUseCase(s, _flow(s)).execute(RetroInput(pending=True))
        self.assertEqual(cadence_count, pending_resp.reflection_count)


class TestRetroLaneVisibility(unittest.TestCase):
    def test_ready_audit_is_in_queue(self):
        q = NodeQueue([Node(id="a", state=State.READY, role="audit", step="audit")])
        self.assertEqual([t.id for t in q.by_lane()["queue"]], ["a"])

    def test_in_progress_audit_is_active(self):
        q = NodeQueue([Node(id="a", state=State.IN_PROGRESS, role="audit", step="audit")])
        self.assertEqual([t.id for t in q.by_lane()["active"]], ["a"])


if __name__ == "__main__":
    unittest.main()
