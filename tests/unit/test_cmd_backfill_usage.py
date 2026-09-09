import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from lightcycle import cli
from lightcycle.ports.workers import RegistryUnreadable
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
    def __init__(self, is_worker=False, is_live_home=True):
        self._is_worker = is_worker
        self._is_live_home = is_live_home

    def data_root(self):
        return "/home"

    def is_worker(self):
        return self._is_worker

    def is_live_home(self):
        return self._is_live_home

    def reconcile_config(self):
        pass

    def usage_pricing(self):
        return {"sonnet": {"input": 2.0, "output": 10.0, "cache_write": 2.5, "cache_read": 0.2}}


class FakeContainer:
    def __init__(self, store=None, fs=None, workers=None, config=None):
        self.store = store or FakeStore()
        self.fs = fs or FakeFs()
        self.workers = workers or FakeWorkers()
        self.config = config or FakeConfig()


class TestCmdBackfillUsage(unittest.TestCase):
    def test_backfill_usage_appears_in_verbs(self):
        self.assertIn("backfill-usage", cli.VERBS)

    def test_reachable_via_main_wired_to_a_fake_container(self):
        with mock.patch.object(cli, "Container", lambda: FakeContainer()):
            rc, out, err = call(cli.main, "backfill-usage")
        self.assertEqual(rc, 0)
        self.assertIn("backfilled", out)

    def test_worker_at_live_home_is_refused(self):
        with mock.patch.object(cli, "Container", lambda: FakeContainer(config=FakeConfig(is_worker=True, is_live_home=True))):
            rc, out, err = call(cli.main, "backfill-usage")
        self.assertEqual(rc, 1)
        self.assertIn("workers may not run 'backfill-usage'", err)


class TestCmdBackfillUsageSummary(unittest.TestCase):
    def test_printed_summary_includes_reclassified_and_recovered_counts(self):
        store = FakeStore()
        store._backfill_log["/l/a.log"] = ("s-1", True)
        store._backfill_log["/l/b.log"] = ("s-2", False)
        fake_resp = mock.Mock(
            stored=1, total=2, matched=1, orphaned=0, unmatched=1, skipped_pending=0,
            reclassified=122, recovered=118,
        )
        with mock.patch.object(cli, "Container", lambda: FakeContainer(store=store)), \
                mock.patch.object(cli, "BackfillUsageUseCase") as UseCase:
            UseCase.return_value.execute.return_value = fake_resp
            rc, out, err = call(cli.main, "backfill-usage")
        self.assertEqual(rc, 0)
        self.assertIn("122/2 ledger rows reclassified", out)
        self.assertIn("118 recovered usage", out)
        self.assertNotIn("repair:", out)

    def test_repair_flag_is_passed_through_and_prints_a_repair_summary(self):
        fake_resp = mock.Mock(
            stored=0, total=0, matched=0, orphaned=0, unmatched=0, skipped_pending=0,
            reclassified=0, recovered=0, repair_examined=5, repair_corrected=2,
            repair_missing_logs=1,
        )
        with mock.patch.object(cli, "Container", lambda: FakeContainer()), \
                mock.patch.object(cli, "BackfillUsageUseCase") as UseCase:
            UseCase.return_value.execute.return_value = fake_resp
            rc, out, err = call(cli.main, "backfill-usage", "--repair")
        self.assertEqual(rc, 0)
        UseCase.return_value.execute.assert_called_once_with(repair=True)
        self.assertIn("repair: 2/5 steps corrected, 1 ledgered logs missing on disk", out)

    def test_unreadable_registry_exits_one_with_a_clean_message(self):
        with mock.patch.object(cli, "Container", lambda: FakeContainer()), \
                mock.patch.object(cli, "BackfillUsageUseCase") as UseCase:
            UseCase.return_value.execute.side_effect = RegistryUnreadable("boom")
            rc, out, err = call(cli.main, "backfill-usage")
        self.assertEqual(rc, 1)
        self.assertNotIn("Traceback", err)
        self.assertIn("boom", err)


if __name__ == "__main__":
    unittest.main()
