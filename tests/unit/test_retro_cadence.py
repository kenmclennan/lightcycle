"""Unit tests for the retro cadence gate."""
import datetime
import unittest

from lightcycle.application.pool.retro_cadence import RetroCadenceUseCase
from lightcycle.application.services.flow import FlowService
from tests.support.fake_fs import FakeFs
from tests.support.fake_store import FakeStore


def _ts(date_str):
    """Convert YYYY-MM-DD to a Unix timestamp (noon UTC)."""
    d = datetime.date.fromisoformat(date_str)
    return float(datetime.datetime(d.year, d.month, d.day, 12, 0, 0).timestamp())


class FakeConfig:
    def __init__(self, interval_days=7, min_epics=3):
        self._interval = interval_days
        self._min = min_epics

    def retro_interval_days(self):
        return self._interval

    def retro_min_epics(self):
        return self._min


def _flow_with_cadence(store, step="trend-check", role="trend-checker"):
    metas = {role: {"model": "sonnet", "step": step, "on_retro_cadence": True}}
    return FlowService(FakeFs(metas), store)


def _flow_without_cadence(store):
    metas = {"coder": {"model": "sonnet", "step": "build"}}
    return FlowService(FakeFs(metas), store)


def _close_theme(store, title, closed_date_str):
    eid = store.create_theme(title)
    store.close(eid, "done")
    store._records[eid]["closed_at"] = closed_date_str + "T12:00:00.000000"
    return eid


def _gate(store, flow_svc, interval_days=7, min_epics=3):
    return RetroCadenceUseCase(store, flow_svc, FakeConfig(interval_days, min_epics))


class TestRetroCadenceNoStep(unittest.TestCase):
    def test_no_cadence_step_does_not_fire(self):
        s = FakeStore()
        gate = _gate(s, _flow_without_cadence(s))
        result = gate.execute(_ts("2026-01-10"))
        self.assertEqual(result.fired, [])


class TestRetroCadenceNoClosed(unittest.TestCase):
    def test_no_closed_epics_does_not_fire(self):
        s = FakeStore()
        gate = _gate(s, _flow_with_cadence(s))
        result = gate.execute(_ts("2026-01-10"))
        self.assertEqual(result.fired, [])


class TestRetroCadenceIntervalGate(unittest.TestCase):
    def _setup(self, interval_days=7, min_epics=3):
        s = FakeStore()
        for i in range(5):
            _close_theme(s, "theme %d" % i, "2025-12-01")
        return s, _flow_with_cadence(s)

    def test_fires_when_interval_elapsed_and_min_epics_met(self):
        s, flow = self._setup()
        gate = _gate(s, flow, interval_days=7, min_epics=3)
        result = gate.execute(_ts("2026-01-01"))
        self.assertEqual(len(result.fired), 1)

    def test_does_not_fire_before_interval_elapsed(self):
        s, flow = self._setup()
        gate = _gate(s, flow, interval_days=30, min_epics=3)
        result = gate.execute(_ts("2025-12-05"))
        self.assertEqual(result.fired, [])

    def test_does_not_fire_with_too_few_epics(self):
        s = FakeStore()
        _close_theme(s, "only one", "2025-12-01")
        flow = _flow_with_cadence(s)
        gate = _gate(s, flow, interval_days=7, min_epics=3)
        result = gate.execute(_ts("2026-01-01"))
        self.assertEqual(result.fired, [])

    def test_fires_exactly_at_min_epics(self):
        s = FakeStore()
        for i in range(3):
            _close_theme(s, "theme %d" % i, "2025-12-01")
        flow = _flow_with_cadence(s)
        gate = _gate(s, flow, interval_days=7, min_epics=3)
        result = gate.execute(_ts("2026-01-01"))
        self.assertEqual(len(result.fired), 1)


class TestRetroCadenceStepMetadata(unittest.TestCase):
    def test_fired_task_has_since_and_fired_at(self):
        s = FakeStore()
        for i in range(3):
            _close_theme(s, "theme %d" % i, "2025-12-01")
        flow = _flow_with_cadence(s)
        gate = _gate(s, flow, interval_days=7, min_epics=3)
        result = gate.execute(_ts("2026-01-01"))
        self.assertEqual(len(result.fired), 1)
        tid = result.fired[0]
        step = s.get_node(tid)
        self.assertEqual(step.since, "2025-12-01")
        self.assertEqual(step.fired_at, "2026-01-01")

    def test_fired_task_at_declared_step_and_role(self):
        s = FakeStore()
        for i in range(3):
            _close_theme(s, "theme %d" % i, "2025-12-01")
        flow = _flow_with_cadence(s, step="trend-scan", role="trend-scanner")
        gate = _gate(s, flow, interval_days=7, min_epics=3)
        result = gate.execute(_ts("2026-01-01"))
        step = s.get_node(result.fired[0])
        self.assertEqual(step.step, "trend-scan")
        self.assertEqual(step.role, "trend-scanner")


class TestRetroCadenceLastFireReference(unittest.TestCase):
    def test_second_fire_uses_fired_at_as_reference(self):
        s = FakeStore()
        for i in range(3):
            _close_theme(s, "first batch theme %d" % i, "2025-12-01")
        flow = _flow_with_cadence(s)
        gate = _gate(s, flow, interval_days=7, min_epics=3)
        result = gate.execute(_ts("2026-01-01"))
        self.assertEqual(len(result.fired), 1)

        for i in range(3):
            _close_theme(s, "second batch theme %d" % i, "2026-01-05")

        result2 = gate.execute(_ts("2026-01-09"))
        self.assertEqual(len(result2.fired), 1)
        task2 = s.get_node(result2.fired[0])
        self.assertEqual(task2.since, "2026-01-01")

    def test_does_not_fire_again_before_interval_from_last_fire(self):
        s = FakeStore()
        for i in range(3):
            _close_theme(s, "theme %d" % i, "2025-12-01")
        flow = _flow_with_cadence(s)
        gate = _gate(s, flow, interval_days=7, min_epics=3)
        gate.execute(_ts("2026-01-01"))

        for i in range(3):
            _close_theme(s, "more theme %d" % i, "2026-01-02")

        result2 = gate.execute(_ts("2026-01-04"))
        self.assertEqual(result2.fired, [])


class TestRetroCadenceClosedFireSeen(unittest.TestCase):

    def _setup_with_closed_fire(self, fired_at_date, step="trend-check", role="trend-checker"):
        s = FakeStore()
        for i in range(3):
            _close_theme(s, "theme %d" % i, "2026-06-01")
        flow = _flow_with_cadence(s, step=step, role=role)
        tid = s.create_step("%s: cross-theme trend audit" % step, step=step, role=role)
        s.update_metadata(tid, {"since": "2026-06-01", "fired_at": fired_at_date})
        s.close(tid, "done")
        return s, flow

    def test_closed_prior_fire_suppresses_tick_within_interval(self):
        s, flow = self._setup_with_closed_fire("2026-07-03")
        gate = _gate(s, flow, interval_days=7, min_epics=3)
        result = gate.execute(_ts("2026-07-05"))
        self.assertEqual(result.fired, [])

    def test_tick_past_interval_from_closed_fire_fires_again(self):
        s, flow = self._setup_with_closed_fire("2026-07-01")
        for i in range(3):
            _close_theme(s, "new theme %d" % i, "2026-07-02")
        gate = _gate(s, flow, interval_days=7, min_epics=3)
        result = gate.execute(_ts("2026-07-09"))
        self.assertEqual(len(result.fired), 1)
        step = s.get_node(result.fired[0])
        self.assertEqual(step.since, "2026-07-01")

    def test_max_fired_at_across_multiple_closed_fires(self):
        s = FakeStore()
        for i in range(3):
            _close_theme(s, "theme %d" % i, "2026-06-01")
        flow = _flow_with_cadence(s)
        for date in ("2026-06-15", "2026-07-01", "2026-06-20"):
            tid = s.create_step("trend-check: audit", step="trend-check", role="trend-checker")
            s.update_metadata(tid, {"since": "2026-06-01", "fired_at": date})
            s.close(tid, "done")
        gate = _gate(s, flow, interval_days=7, min_epics=3)
        result = gate.execute(_ts("2026-07-05"))
        self.assertEqual(result.fired, [])


class TestRetroCadenceAgnostic(unittest.TestCase):
    def test_arbitrary_step_name_fires(self):
        s = FakeStore()
        for i in range(3):
            _close_theme(s, "theme %d" % i, "2025-12-01")
        flow = _flow_with_cadence(s, step="cross-theme-scan", role="cross-scanner")
        gate = _gate(s, flow, interval_days=7, min_epics=3)
        result = gate.execute(_ts("2026-01-01"))
        self.assertEqual(len(result.fired), 1)
        step = s.get_node(result.fired[0])
        self.assertEqual(step.step, "cross-theme-scan")


class TestRetroCadenceMetaRegressGuard(unittest.TestCase):
    def test_retro_origin_epic_excluded_from_window(self):
        s = FakeStore()
        for i in range(2):
            _close_theme(s, "real theme %d" % i, "2025-12-01")
        tagged = _close_theme(s, "retro origin theme", "2025-12-01")
        s.label_add(tagged, "retro-origin")

        flow = _flow_with_cadence(s)
        gate = _gate(s, flow, interval_days=7, min_epics=3)
        result = gate.execute(_ts("2026-01-01"))
        self.assertEqual(result.fired, [])

    def test_non_tagged_epics_count_normally(self):
        s = FakeStore()
        for i in range(3):
            _close_theme(s, "theme %d" % i, "2025-12-01")
        tagged = _close_theme(s, "retro origin theme", "2025-12-01")
        s.label_add(tagged, "retro-origin")

        flow = _flow_with_cadence(s)
        gate = _gate(s, flow, interval_days=7, min_epics=3)
        result = gate.execute(_ts("2026-01-01"))
        self.assertEqual(len(result.fired), 1)


if __name__ == "__main__":
    unittest.main()
