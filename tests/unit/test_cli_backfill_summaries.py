import datetime
import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from lightcycle import cli
from lightcycle.adapters.claude_stream import ClaudeStreamAdapter
from tests.support.fake_fs import FakeFs
from tests.support.fake_store import FakeStore


def call(fn, *args):
    out, err = io.StringIO(), io.StringIO()
    try:
        with redirect_stdout(out), redirect_stderr(err):
            rc = fn(list(args)) or 0
    except SystemExit as e:
        rc = e.code if isinstance(e.code, int) else 1
    return rc, out.getvalue(), err.getvalue()


class FakeWorkers:
    def workers_state(self):
        return []


class FakeConfig:
    def __init__(self, is_worker=False, is_live_home=True, summary_shortcode="SUM"):
        self._is_worker = is_worker
        self._is_live_home = is_live_home
        self._summary_shortcode = summary_shortcode

    def data_root(self):
        return "/home"

    def is_worker(self):
        return self._is_worker

    def is_live_home(self):
        return self._is_live_home

    def reconcile_config(self):
        pass

    def summary_shortcode(self):
        return self._summary_shortcode


class FakeContainer:
    def __init__(self, store=None, fs=None, workers=None, config=None, worker_log=None):
        self.store = store or FakeStore()
        self.fs = fs or FakeFs()
        self.workers = workers or FakeWorkers()
        self.config = config or FakeConfig()
        self.worker_log = worker_log if worker_log is not None else self.fs
        self.claude_stream = ClaudeStreamAdapter()


_TODAY = datetime.date(2026, 1, 10)
_NOW_EPOCH = datetime.datetime.combine(_TODAY, datetime.time(12, 0)).astimezone().timestamp()


def _close_item(store, day, title="item"):
    item = store.create_item(title, "a description")
    store.complete_node(item, "merged", disposition="completed")
    store._records[item]["closed_at"] = (
        datetime.datetime.combine(day, datetime.time(10, 0)).astimezone().isoformat()
    )
    return item


def _run_backfill():
    with mock.patch.object(cli.time, "time", return_value=_NOW_EPOCH):
        return call(cli.main, "backfill-summaries")


class TestCmdBackfillSummaries(unittest.TestCase):
    def test_appears_in_verbs(self):
        self.assertIn("backfill-summaries", cli.VERBS)

    def test_spawns_one_step_per_day_with_activity_in_the_last_seven_days(self):
        store = FakeStore()
        active_days = [_TODAY - datetime.timedelta(days=n) for n in (2, 4, 6)]
        for day in active_days:
            _close_item(store, day)
        with mock.patch.object(cli, "Container", lambda: FakeContainer(store=store)):
            rc, out, err = _run_backfill()

        self.assertEqual(rc, 0)
        self.assertIn("backfilled 3 day(s)", out)
        for day in active_days:
            row = store.day_summary(day)
            self.assertIsNotNone(row)
            self.assertIsNotNone(row.step_id)
            self.assertEqual(row.spawn_count, 1)

    def test_today_itself_is_never_backfilled(self):
        store = FakeStore()
        _close_item(store, _TODAY)
        with mock.patch.object(cli, "Container", lambda: FakeContainer(store=store)):
            rc, out, err = _run_backfill()

        self.assertEqual(rc, 0)
        self.assertIn("backfilled 0 day(s)", out)
        self.assertIsNone(store.day_summary(_TODAY))

    def test_running_twice_is_idempotent(self):
        store = FakeStore()
        active_days = [_TODAY - datetime.timedelta(days=n) for n in (2, 4)]
        for day in active_days:
            _close_item(store, day)
        with mock.patch.object(cli, "Container", lambda: FakeContainer(store=store)):
            first_rc, first_out, _ = _run_backfill()
            second_rc, second_out, _ = _run_backfill()

        self.assertEqual(first_rc, 0)
        self.assertEqual(second_rc, 0)
        self.assertIn("backfilled 2 day(s)", first_out)
        self.assertIn("backfilled 0 day(s)", second_out)

    def test_a_day_already_being_generated_by_the_live_cadence_gate_is_skipped_not_double_spawned(self):
        store = FakeStore()
        day = _TODAY - datetime.timedelta(days=2)
        _close_item(store, day)
        with store.transaction():
            item = store.create_item("Daily summary: %s" % day.isoformat(), "in flight")
            store.label_add(item, "summary-origin")
            tid = store.create_step(step="daily-summary", role="agent", parent=item)
            store.mark_day_summary_dirty(day)
            store.start_day_summary(day, step_id=tid, spawn_count=1)
        with mock.patch.object(cli, "Container", lambda: FakeContainer(store=store)):
            rc, out, err = _run_backfill()

        self.assertEqual(rc, 0)
        self.assertIn("backfilled 0 day(s)", out)
        self.assertEqual(store.day_summary(day).step_id, tid)


if __name__ == "__main__":
    unittest.main()
