import io
import unittest
from contextlib import redirect_stderr
from unittest import mock

from lightcycle import cli
from lightcycle.cli import _worker_permitted
from lightcycle.config import Config


class TestWorkerPermitted(unittest.TestCase):
    def test_core_verbs_allowed(self):
        for v in ("claim", "done", "show", "attach"):
            self.assertTrue(_worker_permitted(v, ["ITEM.1"]), v)

    def test_retro_allowed_for_the_audit_worker(self):
        self.assertTrue(_worker_permitted("retro", ["--pending"]))

    def test_destructive_verbs_forbidden(self):
        for v in ("rm", "init", "new", "start", "sweep", "dep", "backlog", "config",
                  "workflow"):
            self.assertFalse(_worker_permitted(v, ["x"]), v)

    def test_set_state_blocked_allowed(self):
        self.assertTrue(_worker_permitted(
            "set", ["ITEM.1", "--state", "blocked", "--needs", "human", "--branch", "b"]))

    def test_set_state_blocked_equals_form_allowed(self):
        self.assertTrue(_worker_permitted("set", ["ITEM.1", "--state=blocked"]))

    def test_set_parent_forbidden(self):
        self.assertFalse(_worker_permitted("set", ["ITEM", "--parent", "THEME"]))

    def test_set_state_active_forbidden(self):
        self.assertFalse(_worker_permitted("set", ["ITEM", "--state", "active"]))

    def test_set_without_state_forbidden(self):
        self.assertFalse(_worker_permitted("set", ["ITEM", "--title", "x"]))

    def test_set_parent_alongside_blocked_still_forbidden(self):
        self.assertFalse(_worker_permitted("set", ["ITEM", "--state", "blocked", "--parent", "T"]))


class TestIsWorker(unittest.TestCase):
    def test_true_when_flag_set(self):
        self.assertTrue(Config(environ={"LC_WORKER": "1"}).is_worker())

    def test_false_when_absent(self):
        self.assertFalse(Config(environ={}).is_worker())


class TestIsLiveHome(unittest.TestCase):
    def test_true_when_unset(self):
        self.assertTrue(Config(environ={}).is_live_home())

    def test_true_when_explicit_override_matches_default(self):
        default = Config(environ={}).default_data_root()
        self.assertTrue(Config(environ={"LC_HOME": default}).is_live_home())

    def test_false_when_override_is_a_scratch_dir(self):
        self.assertFalse(
            Config(environ={"LC_HOME": "/tmp/some-scratch-store"}).is_live_home()
        )


class _GateCfg:
    def __init__(self, is_live_home):
        self._is_live_home = is_live_home

    def is_worker(self):
        return True

    def is_live_home(self):
        return self._is_live_home

    def reconcile_config(self):
        pass


class _GateContainer:
    def __init__(self, is_live_home):
        self.config = _GateCfg(is_live_home)


class TestMainWorkerGateKeysOnLiveHome(unittest.TestCase):
    def test_worker_at_live_home_refused(self):
        with mock.patch.object(cli, "Container", lambda: _GateContainer(True)):
            err = io.StringIO()
            with redirect_stderr(err):
                rc = cli.main(["rm", "X"])
        self.assertEqual(rc, 1)
        self.assertIn("workers may not run 'rm'", err.getvalue())

    def test_worker_at_non_live_home_not_gate_refused(self):
        with mock.patch.object(cli, "Container", lambda: _GateContainer(False)), \
                mock.patch.object(cli, "cmd_rm", lambda argv: 0):
            err = io.StringIO()
            with redirect_stderr(err):
                rc = cli.main(["rm", "X"])
        self.assertEqual(rc, 0)
        self.assertNotIn("workers may not run", err.getvalue())


if __name__ == "__main__":
    unittest.main()
