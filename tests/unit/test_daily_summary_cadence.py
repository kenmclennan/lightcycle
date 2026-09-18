import datetime
import unittest

from lightcycle.application.flow.engine_steps import (
    DAILY_SUMMARY_STEP, SUMMARY_ORIGIN_LABEL,
)
from lightcycle.application.pool.daily_summary_cadence import (
    DailySummaryCadenceUseCase, _SCAN_INTERVAL_SECONDS,
)
from lightcycle.application.flow.complete_step import CompleteInput, CompleteStepUseCase
from tests.support.fake_store import FakeStore
from tests.unit.test_flow_usecases import METAS, flow_for


class FakeConfig:
    def __init__(self, debounce_seconds=600, internal_shortcode="AUD"):
        self._debounce_seconds = debounce_seconds
        self._internal_shortcode = internal_shortcode

    def daily_summary_debounce_seconds(self):
        return self._debounce_seconds

    def internal_shortcode(self):
        return self._internal_shortcode


class _Clock:
    def __init__(self, epoch):
        self.epoch = epoch

    def iso(self):
        return datetime.datetime.fromtimestamp(self.epoch).astimezone().isoformat()


def _epoch(day, hour=12):
    return datetime.datetime.combine(day, datetime.time(hour, 0)).astimezone().timestamp()


def _make_store_and_clock(start_epoch):
    clock = _Clock(start_epoch)
    store = FakeStore(now=clock.iso)
    return store, clock


def _tick(gate, clock, epoch):
    clock.epoch = epoch
    return gate.execute(epoch)


def _close_item(store, day, title="item", hour=10):
    item = store.create_item(title, "a description")
    store.complete_node(item, "merged", disposition="completed")
    store._records[item]["closed_at"] = (
        datetime.datetime.combine(day, datetime.time(hour, 0)).astimezone().isoformat()
    )
    return item


def _gate(store, debounce_seconds=600, internal_shortcode="AUD"):
    return DailySummaryCadenceUseCase(store, FakeConfig(debounce_seconds, internal_shortcode))


def _spy_all_items_calls(store):
    calls = {"n": 0}
    original = store.all_items_including_done

    def counted():
        calls["n"] += 1
        return original()

    store.all_items_including_done = counted
    return calls


class TestDailySummaryCadenceDiscovery(unittest.TestCase):
    def test_a_dirty_free_day_with_new_activity_is_marked_dirty_but_fires_nothing(self):
        day = datetime.date(2026, 1, 1)
        store, clock = _make_store_and_clock(_epoch(day))
        _close_item(store, day)
        gate = _gate(store)

        result = _tick(gate, clock, _epoch(day))

        self.assertEqual(result.fired, [])
        row = store.day_summary(day)
        self.assertIsNotNone(row)
        self.assertIsNotNone(row.dirty_since)

    def test_a_day_with_nothing_closed_is_never_marked_dirty(self):
        day = datetime.date(2026, 1, 1)
        store, clock = _make_store_and_clock(_epoch(day))
        gate = _gate(store)

        _tick(gate, clock, _epoch(day))

        self.assertIsNone(store.day_summary(day))


class TestDailySummaryCadenceDebounce(unittest.TestCase):
    def test_a_day_dirty_for_less_than_the_debounce_fires_nothing(self):
        day = datetime.date(2026, 1, 1)
        store, clock = _make_store_and_clock(_epoch(day))
        _close_item(store, day)
        gate = _gate(store, debounce_seconds=600)
        _tick(gate, clock, _epoch(day))

        result = _tick(gate, clock, _epoch(day) + 599)

        self.assertEqual(result.fired, [])

    def test_a_day_dirty_for_at_least_the_debounce_spawns(self):
        day = datetime.date(2026, 1, 1)
        store, clock = _make_store_and_clock(_epoch(day))
        _close_item(store, day)
        gate = _gate(store, debounce_seconds=600)
        _tick(gate, clock, _epoch(day))

        result = _tick(gate, clock, _epoch(day) + 700)

        self.assertEqual(len(result.fired), 1)

    def test_a_day_exactly_at_the_debounce_boundary_fires(self):
        day = datetime.date(2026, 1, 1)
        store, clock = _make_store_and_clock(_epoch(day))
        _close_item(store, day)
        gate = _gate(store, debounce_seconds=600)
        _tick(gate, clock, _epoch(day))

        result = _tick(gate, clock, _epoch(day) + 600)

        self.assertEqual(len(result.fired), 1)

    def test_spawn_creates_item_and_step_and_links_the_day_row(self):
        day = datetime.date(2026, 1, 1)
        store, clock = _make_store_and_clock(_epoch(day))
        _close_item(store, day)
        gate = _gate(store, debounce_seconds=600)
        _tick(gate, clock, _epoch(day))

        result = _tick(gate, clock, _epoch(day) + 700)

        tid = result.fired[0]
        step = store.get_node(tid)
        self.assertEqual(step.stage, DAILY_SUMMARY_STEP)
        self.assertEqual(step.role, "agent")
        self.assertIn(SUMMARY_ORIGIN_LABEL, store.labels_of(step.item))
        row = store.day_summary(day)
        self.assertEqual(row.step_id, tid)
        self.assertEqual(row.spawn_count, 1)


class TestDailySummaryCadenceOpenGuard(unittest.TestCase):
    def test_an_already_open_summary_step_blocks_a_second_spawn_for_today_or_yesterday(self):
        today = datetime.date(2026, 1, 2)
        yesterday = datetime.date(2026, 1, 1)
        store, clock = _make_store_and_clock(_epoch(today))
        _close_item(store, today)
        _close_item(store, yesterday)
        gate = _gate(store, debounce_seconds=600)
        _tick(gate, clock, _epoch(today))

        first = _tick(gate, clock, _epoch(today) + 700)
        self.assertEqual(len(first.fired), 1)

        second = _tick(gate, clock, _epoch(today) + 700)
        self.assertEqual(second.fired, [])
        self.assertIsNone(store.day_summary(yesterday).step_id)


class TestDailySummaryCadenceWindow(unittest.TestCase):
    def test_a_day_three_days_old_is_never_examined(self):
        today = datetime.date(2026, 1, 4)
        old_day = datetime.date(2026, 1, 1)
        store, clock = _make_store_and_clock(_epoch(today))
        _close_item(store, old_day)
        gate = _gate(store, debounce_seconds=600)

        for _ in range(5):
            _tick(gate, clock, _epoch(today))

        self.assertIsNone(store.day_summary(old_day))


class TestDailySummaryCadenceScanThrottle(unittest.TestCase):
    def test_one_tick_scans_both_today_and_yesterday_while_both_are_clean(self):
        day = datetime.date(2026, 1, 1)
        store, clock = _make_store_and_clock(_epoch(day))
        gate = _gate(store)
        calls = _spy_all_items_calls(store)

        _tick(gate, clock, _epoch(day))

        self.assertEqual(calls["n"], 2)

    def test_a_second_tick_within_the_scan_interval_adds_no_further_scans(self):
        day = datetime.date(2026, 1, 1)
        store, clock = _make_store_and_clock(_epoch(day))
        gate = _gate(store)
        calls = _spy_all_items_calls(store)

        _tick(gate, clock, _epoch(day))
        _tick(gate, clock, _epoch(day) + (_SCAN_INTERVAL_SECONDS - 1))

        self.assertEqual(calls["n"], 2)

    def test_a_tick_past_the_scan_interval_rescans_both_still_clean_days(self):
        day = datetime.date(2026, 1, 1)
        store, clock = _make_store_and_clock(_epoch(day))
        gate = _gate(store)
        calls = _spy_all_items_calls(store)

        _tick(gate, clock, _epoch(day))
        _tick(gate, clock, _epoch(day) + _SCAN_INTERVAL_SECONDS + 1)

        self.assertEqual(calls["n"], 4)

    def test_a_dirty_day_is_checked_every_tick_with_no_further_scan_within_the_interval(self):
        day = datetime.date(2026, 1, 1)
        store, clock = _make_store_and_clock(_epoch(day))
        _close_item(store, day)
        gate = _gate(store, debounce_seconds=600)
        _tick(gate, clock, _epoch(day))
        calls = _spy_all_items_calls(store)

        _tick(gate, clock, _epoch(day) + 10)
        _tick(gate, clock, _epoch(day) + 20)
        _tick(gate, clock, _epoch(day) + 30)

        self.assertEqual(calls["n"], 0)


if __name__ == "__main__":
    unittest.main()


class TestDailySummaryCadenceSettles(unittest.TestCase):
    def test_a_completed_summary_does_not_respawn_for_a_day_with_no_new_real_work(self):
        day = datetime.date(2026, 1, 1)
        store, clock = _make_store_and_clock(_epoch(day))
        _close_item(store, day)
        gate = _gate(store, debounce_seconds=600)
        _tick(gate, clock, _epoch(day))
        tid = _tick(gate, clock, _epoch(day) + 700).fired[0]
        clock.epoch = _epoch(day) + 710
        store.add_artifact(tid, "summary", "what shipped")

        CompleteStepUseCase(store, flow_for(METAS, store)).execute(
            CompleteInput(step=tid, outcome="done"))

        self.assertIsNone(store.day_summary(day).dirty_since)
        for offset in (800, 1600, 2400):
            self.assertEqual(_tick(gate, clock, _epoch(day) + offset).fired, [])
