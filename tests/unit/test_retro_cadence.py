import unittest

from lightcycle.application.pool.retro_cadence import RetroCadenceUseCase
from lightcycle.application.services.flow import FlowService
from lightcycle.domain.work import Node, NodeQueue, State
from tests.support.fake_fs import FakeFs
from tests.support.fake_store import FakeStore


class FakeConfig:
    def __init__(self, interval_items=3, engine="lightcycle"):
        self._interval = interval_items
        self._engine = engine

    def retro_interval_items(self):
        return self._interval

    def engine_root(self):
        return "/w/projects/%s" % self._engine


def _flow_with_cadence(store, step="trend-check", role="trend-checker"):
    metas = {role: {"model": "sonnet", "step": step, "on_retro_cadence": True}}
    return FlowService(FakeFs(metas), store)


def _flow_without_cadence(store):
    metas = {"coder": {"model": "sonnet", "step": "build"}}
    return FlowService(FakeFs(metas), store)


def _close_item(store, title, project=None, theme=None):
    eid = store.create_item(title, theme=theme)
    store.close(eid, "done")
    if project is not None:
        store.add_artifact(eid, "repo", project)
    return eid


def _gate(store, flow_svc, interval_items=3, engine="lightcycle"):
    return RetroCadenceUseCase(store, flow_svc, FakeConfig(interval_items, engine))


class TestRetroCadenceNoFire(unittest.TestCase):
    def test_no_cadence_step_does_not_fire(self):
        s = FakeStore()
        self.assertEqual(_gate(s, _flow_without_cadence(s)).execute(0.0).fired, [])

    def test_no_closed_items_does_not_fire(self):
        s = FakeStore()
        self.assertEqual(_gate(s, _flow_with_cadence(s)).execute(0.0).fired, [])

    def test_below_threshold_does_not_fire(self):
        s = FakeStore()
        for i in range(2):
            _close_item(s, "item %d" % i, project="lightcycle")
        self.assertEqual(_gate(s, _flow_with_cadence(s), interval_items=3).execute(0.0).fired, [])


class TestRetroCadenceFires(unittest.TestCase):
    def test_threshold_fires_one_audit_scoped_to_project(self):
        s = FakeStore()
        for i in range(3):
            _close_item(s, "item %d" % i, project="lightcycle")
        result = _gate(s, _flow_with_cadence(s), interval_items=3).execute(0.0)
        self.assertEqual(len(result.fired), 1)
        self.assertEqual(s.get_node(result.fired[0]).project, "lightcycle")

    def test_items_without_repo_use_engine_default(self):
        s = FakeStore()
        for i in range(3):
            _close_item(s, "item %d" % i)
        result = _gate(s, _flow_with_cadence(s), interval_items=3, engine="lightcycle").execute(0.0)
        self.assertEqual(len(result.fired), 1)
        self.assertEqual(s.get_node(result.fired[0]).project, "lightcycle")

    def test_fired_audit_at_declared_step_and_role(self):
        s = FakeStore()
        for i in range(3):
            _close_item(s, "item %d" % i, project="lightcycle")
        flow = _flow_with_cadence(s, step="trend-scan", role="trend-scanner")
        step = s.get_node(_gate(s, flow, interval_items=3).execute(0.0).fired[0])
        self.assertEqual(step.step, "trend-scan")
        self.assertEqual(step.role, "trend-scanner")


class TestRetroCadenceNoRunaway(unittest.TestCase):
    def test_does_not_refire_while_an_audit_is_open(self):
        s = FakeStore()
        for i in range(3):
            _close_item(s, "item %d" % i, project="lightcycle")
        gate = _gate(s, _flow_with_cadence(s), interval_items=3)
        self.assertEqual(len(gate.execute(0.0).fired), 1)
        self.assertEqual(gate.execute(0.0).fired, [])

    def test_marked_batch_does_not_refire_after_audit_closes(self):
        s = FakeStore()
        items = [_close_item(s, "item %d" % i, project="lightcycle") for i in range(3)]
        gate = _gate(s, _flow_with_cadence(s), interval_items=3)
        first = gate.execute(0.0)
        for item in items:
            s.label_add(item, "retroed")
        s.close(first.fired[0], "clean")
        self.assertEqual(gate.execute(0.0).fired, [])

    def test_refires_for_a_fresh_batch(self):
        s = FakeStore()
        items = [_close_item(s, "item %d" % i, project="lightcycle") for i in range(3)]
        gate = _gate(s, _flow_with_cadence(s), interval_items=3)
        first = gate.execute(0.0)
        for item in items:
            s.label_add(item, "retroed")
        s.close(first.fired[0], "clean")
        for i in range(3):
            _close_item(s, "fresh %d" % i, project="lightcycle")
        self.assertEqual(len(gate.execute(0.0).fired), 1)


class TestRetroCadencePerProject(unittest.TestCase):
    def test_projects_count_independently(self):
        s = FakeStore()
        for i in range(3):
            _close_item(s, "lc %d" % i, project="lightcycle")
        for i in range(2):
            _close_item(s, "saga %d" % i, project="saga")
        result = _gate(s, _flow_with_cadence(s), interval_items=3).execute(0.0)
        self.assertEqual(len(result.fired), 1)
        self.assertEqual(s.get_node(result.fired[0]).project, "lightcycle")

    def test_each_project_over_threshold_fires_its_own_audit(self):
        s = FakeStore()
        for i in range(3):
            _close_item(s, "lc %d" % i, project="lightcycle")
        for i in range(3):
            _close_item(s, "saga %d" % i, project="saga")
        result = _gate(s, _flow_with_cadence(s), interval_items=3).execute(0.0)
        self.assertEqual(sorted(s.get_node(t).project for t in result.fired), ["lightcycle", "saga"])


class TestRetroCadenceExcludes(unittest.TestCase):
    def test_retro_origin_item_excluded(self):
        s = FakeStore()
        for i in range(2):
            _close_item(s, "real %d" % i, project="lightcycle")
        s.label_add(_close_item(s, "retro origin", project="lightcycle"), "retro-origin")
        self.assertEqual(_gate(s, _flow_with_cadence(s), interval_items=3).execute(0.0).fired, [])

    def test_retroed_item_excluded(self):
        s = FakeStore()
        for i in range(2):
            _close_item(s, "real %d" % i, project="lightcycle")
        s.label_add(_close_item(s, "already retroed", project="lightcycle"), "retroed")
        self.assertEqual(_gate(s, _flow_with_cadence(s), interval_items=3).execute(0.0).fired, [])


class TestRetroLaneVisibility(unittest.TestCase):
    def test_ready_audit_is_in_queue(self):
        q = NodeQueue([Node(id="a", state=State.READY, role="trend-checker", step="trend-check")])
        self.assertEqual([t.id for t in q.by_lane()["queue"]], ["a"])

    def test_in_progress_audit_is_active(self):
        q = NodeQueue([Node(id="a", state=State.IN_PROGRESS, role="trend-checker", step="trend-check")])
        self.assertEqual([t.id for t in q.by_lane()["active"]], ["a"])

    def test_ready_review_findings_is_in_inbox(self):
        q = NodeQueue([Node(id="r", state=State.READY, role="human", step="review-findings")])
        self.assertEqual([t.id for t in q.by_lane()["inbox"]], ["r"])


if __name__ == "__main__":
    unittest.main()
