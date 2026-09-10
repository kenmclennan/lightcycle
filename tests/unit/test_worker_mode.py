import io
import unittest
from contextlib import redirect_stderr
from unittest import mock

from lightcycle import cli
from lightcycle.config import Config
from lightcycle.domain.work import worker_permitted


class TestWorkerPermitted(unittest.TestCase):
    def test_core_verbs_allowed(self):
        for v in ("claim", "done", "show", "attach"):
            self.assertTrue(worker_permitted(v, {}), v)

    def test_retro_allowed_for_the_audit_worker(self):
        self.assertTrue(worker_permitted("retro", {}))

    def test_backlog_allowed_for_the_audit_worker(self):
        self.assertTrue(worker_permitted("backlog", {}))

    def test_search_allowed_for_the_audit_worker(self):
        self.assertTrue(worker_permitted("search", {}))

    def test_peek_allowed_for_the_audit_worker(self):
        self.assertTrue(worker_permitted("peek", {}))

    def test_destructive_verbs_forbidden(self):
        for v in ("rm", "init", "new", "start", "sweep", "dep", "config",
                  "workflow", "backfill-usage"):
            self.assertFalse(worker_permitted(v, {}), v)

    def test_set_state_waiting_allowed(self):
        self.assertTrue(worker_permitted(
            "set", cli._set_flags(["ITEM.1", "--state", "waiting", "--needs", "human", "--branch", "b"])
        ))

    def test_set_state_waiting_equals_form_allowed(self):
        self.assertTrue(worker_permitted("set", cli._set_flags(["ITEM.1", "--state=waiting"])))

    def test_set_parent_forbidden(self):
        self.assertFalse(worker_permitted("set", cli._set_flags(["STEP", "--parent", "ITEM"])))

    def test_set_state_active_forbidden(self):
        self.assertFalse(worker_permitted("set", cli._set_flags(["ITEM", "--state", "active"])))

    def test_set_without_state_forbidden(self):
        self.assertFalse(worker_permitted("set", cli._set_flags(["ITEM", "--title", "x"])))

    def test_an_edit_flag_alongside_waiting_is_still_forbidden(self):
        self.assertFalse(worker_permitted(
            "set", cli._set_flags(["ITEM", "--state", "waiting", "--title", "renamed"])
        ))

    def test_unset_without_state_forbidden(self):
        self.assertFalse(worker_permitted("set", cli._set_flags(["ITEM", "--unset", "description"])))

    def test_unset_alongside_waiting_is_still_forbidden(self):
        self.assertFalse(worker_permitted(
            "set", cli._set_flags(["ITEM", "--state", "waiting", "--unset", "description"])
        ))

    def test_abbreviated_forbidden_flag_no_longer_slips_past_the_check(self):
        self.assertFalse(worker_permitted(
            "set", cli._set_flags(["ITEM", "--state", "waiting", "--titl", "foo"])
        ))

    def test_bare_set_with_no_id_fails_via_argparse_not_the_gate(self):
        with self.assertRaises(SystemExit) as ctx:
            cli._set_flags([])
        self.assertEqual(ctx.exception.code, 2)


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
