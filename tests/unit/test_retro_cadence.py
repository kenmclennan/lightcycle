import datetime
import unittest

from lightcycle.application.pool.retro_cadence import RetroCadenceUseCase
from lightcycle.application.services.flow import FlowService
from lightcycle.domain.work import Node, NodeQueue, State
from tests.support.fake_fs import FakeFs
from tests.support.fake_store import FakeStore


def _ts(date_str):
    d = datetime.date.fromisoformat(date_str)
    return float(datetime.datetime(d.year, d.month, d.day, 12, 0, 0).timestamp())


class FakeConfig:
    def __init__(self, interval_items=3):
        self._interval = interval_items

    def retro_interval_items(self):
        return self._interval


def _flow_with_cadence(store, step="trend-check", role="trend-checker"):
    metas = {role: {"model": "sonnet", "step": step, "on_retro_cadence": True}}
    return FlowService(FakeFs(metas), store)


def _flow_without_cadence(store):
    metas = {"coder": {"model": "sonnet", "step": "build"}}
    return FlowService(FakeFs(metas), store)


def _close_item(store, title, closed_date_str, theme=None):
    eid = store.create_item(title, theme=theme)
    store.close(eid, "done")
    store._records[eid]["closed_at"] = closed_date_str + "T12:00:00.000000"
    return eid


def _gate(store, flow_svc, interval_items=3):
    return RetroCadenceUseCase(store, flow_svc, FakeConfig(interval_items))


class TestRetroCadenceNoStep(unittest.TestCase):
    def test_no_cadence_step_does_not_fire(self):
        s = FakeStore()
        gate = _gate(s, _flow_without_cadence(s))
        result = gate.execute(_ts("2026-01-10"))
        self.assertEqual(result.fired, [])


class TestRetroCadenceNoClosed(unittest.TestCase):
    def test_no_closed_items_does_not_fire(self):
        s = FakeStore()
        gate = _gate(s, _flow_with_cadence(s))
        result = gate.execute(_ts("2026-01-10"))
        self.assertEqual(result.fired, [])


class TestRetroCadenceCountGate(unittest.TestCase):
    def test_n_minus_one_closed_items_does_not_fire(self):
        s = FakeStore()
        for i in range(2):
            _close_item(s, "item %d" % i, "2025-12-01")
        flow = _flow_with_cadence(s)
        gate = _gate(s, flow, interval_items=3)
        result = gate.execute(_ts("2026-01-01"))
        self.assertEqual(result.fired, [])

    def test_nth_closed_item_fires_one_audit_with_since_reference(self):
        s = FakeStore()
        for i in range(3):
            _close_item(s, "item %d" % i, "2025-12-01")
        flow = _flow_with_cadence(s)
        gate = _gate(s, flow, interval_items=3)
        result = gate.execute(_ts("2026-01-01"))
        self.assertEqual(len(result.fired), 1)
        step = s.get_node(result.fired[0])
        self.assertEqual(step.since, "2025-12-01")
        self.assertEqual(step.fired_at, "2026-01-01")

    def test_themed_and_loose_items_both_count(self):
        s = FakeStore()
        theme = s.create_theme("some theme")
        _close_item(s, "themed item", "2025-12-01", theme=theme)
        _close_item(s, "another themed item", "2025-12-01", theme=theme)
        _close_item(s, "loose item", "2025-12-01")
        flow = _flow_with_cadence(s)
        gate = _gate(s, flow, interval_items=3)
        result = gate.execute(_ts("2026-01-01"))
        self.assertEqual(len(result.fired), 1)

    def test_fired_task_at_declared_step_and_role(self):
        s = FakeStore()
        for i in range(3):
            _close_item(s, "item %d" % i, "2025-12-01")
        flow = _flow_with_cadence(s, step="trend-scan", role="trend-scanner")
        gate = _gate(s, flow, interval_items=3)
        result = gate.execute(_ts("2026-01-01"))
        step = s.get_node(result.fired[0])
        self.assertEqual(step.step, "trend-scan")
        self.assertEqual(step.role, "trend-scanner")


class TestRetroCadenceDoesNotDoubleFire(unittest.TestCase):
    def test_second_tick_before_n_more_close_does_not_double_fire(self):
        s = FakeStore()
        for i in range(3):
            _close_item(s, "item %d" % i, "2025-12-01")
        flow = _flow_with_cadence(s)
        gate = _gate(s, flow, interval_items=3)
        first = gate.execute(_ts("2026-01-01"))
        self.assertEqual(len(first.fired), 1)

        _close_item(s, "one more", "2026-01-02")
        second = gate.execute(_ts("2026-01-03"))
        self.assertEqual(second.fired, [])


class TestRetroCadenceReferenceAdvances(unittest.TestCase):
    def test_reference_advances_after_a_fire(self):
        s = FakeStore()
        for i in range(3):
            _close_item(s, "first batch %d" % i, "2025-12-01")
        flow = _flow_with_cadence(s)
        gate = _gate(s, flow, interval_items=3)
        first = gate.execute(_ts("2026-01-01"))
        self.assertEqual(len(first.fired), 1)

        for i in range(3):
            _close_item(s, "second batch %d" % i, "2026-01-05")

        second = gate.execute(_ts("2026-01-09"))
        self.assertEqual(len(second.fired), 1)
        step2 = s.get_node(second.fired[0])
        self.assertEqual(step2.since, "2026-01-01")


class TestRetroCadenceAgnostic(unittest.TestCase):
    def test_arbitrary_step_name_fires(self):
        s = FakeStore()
        for i in range(3):
            _close_item(s, "item %d" % i, "2025-12-01")
        flow = _flow_with_cadence(s, step="cross-theme-scan", role="cross-scanner")
        gate = _gate(s, flow, interval_items=3)
        result = gate.execute(_ts("2026-01-01"))
        self.assertEqual(len(result.fired), 1)
        step = s.get_node(result.fired[0])
        self.assertEqual(step.step, "cross-theme-scan")


class TestRetroCadenceMetaRegressGuard(unittest.TestCase):
    def test_retro_origin_item_excluded_from_window(self):
        s = FakeStore()
        for i in range(2):
            _close_item(s, "real item %d" % i, "2025-12-01")
        tagged = _close_item(s, "retro origin item", "2025-12-01")
        s.label_add(tagged, "retro-origin")

        flow = _flow_with_cadence(s)
        gate = _gate(s, flow, interval_items=3)
        result = gate.execute(_ts("2026-01-01"))
        self.assertEqual(result.fired, [])


class TestRetroLaneVisibility(unittest.TestCase):
    def test_ready_audit_is_in_queue(self):
        q = NodeQueue([Node(id="a", state=State.READY, role="trend-checker", step="trend-check")])
        self.assertEqual([t.id for t in q.by_lane()["queue"]], ["a"])

    def test_in_progress_audit_is_active(self):
        q = NodeQueue(
            [Node(id="a", state=State.IN_PROGRESS, role="trend-checker", step="trend-check")]
        )
        self.assertEqual([t.id for t in q.by_lane()["active"]], ["a"])

    def test_ready_review_findings_is_in_inbox(self):
        q = NodeQueue([Node(id="r", state=State.READY, role="human", step="review-findings")])
        self.assertEqual([t.id for t in q.by_lane()["inbox"]], ["r"])


if __name__ == "__main__":
    unittest.main()
