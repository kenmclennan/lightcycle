import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from lightcycle import cli
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


if __name__ == "__main__":
    unittest.main()
