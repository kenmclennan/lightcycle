import unittest

from lightcycle.application.pool.backup import BackupResponse
from lightcycle.application.pool.breaker_gate import BreakerGateResponse
from lightcycle.application.pool.hook_completions import HookCompletionsResponse
from lightcycle.application.pool.monitor_prs import MonitorPrsResponse
from lightcycle.application.pool.no_op_gates import (
    NoOpBackupGate,
    NoOpBreakerGate,
    NoOpCadenceGate,
    NoOpFlowService,
    NoOpFs,
    NoOpGit,
    NoOpHookCompletions,
    NoOpMonitor,
    NoOpSpinPort,
    NoOpStream,
    NoOpUsageGate,
    NoOpWorktrees,
)
from lightcycle.application.pool.retro_cadence import RetroCadenceResponse
from lightcycle.domain.pool import Breaker
from lightcycle.domain.pool.spin_ledger import SpinLedger
from lightcycle.ports.git import GitReadError


class TestNoOpMonitor(unittest.TestCase):
    def test_execute_returns_empty_merged(self):
        self.assertEqual(NoOpMonitor().execute(), MonitorPrsResponse(merged=[]))


class TestNoOpCadenceGate(unittest.TestCase):
    def test_execute_returns_no_fired(self):
        self.assertEqual(NoOpCadenceGate().execute(now=1.0), RetroCadenceResponse())


class TestNoOpBreakerGate(unittest.TestCase):
    def test_execute_returns_closed_breaker(self):
        self.assertEqual(
            NoOpBreakerGate().execute(now=1.0), BreakerGateResponse(breaker=Breaker())
        )


class TestNoOpHookCompletions(unittest.TestCase):
    def test_execute_returns_no_completions(self):
        self.assertEqual(NoOpHookCompletions().execute(since=1.0), HookCompletionsResponse())


class TestNoOpBackupGate(unittest.TestCase):
    def test_execute_returns_no_backup(self):
        self.assertEqual(NoOpBackupGate().execute(now=1.0), BackupResponse())


class TestNoOpUsageGate(unittest.TestCase):
    def test_execute_returns_none_and_does_not_raise(self):
        self.assertIsNone(NoOpUsageGate().execute(now=1.0))


class TestNoOpFlowService(unittest.TestCase):
    def test_clear_cache_does_nothing(self):
        self.assertIsNone(NoOpFlowService().clear_cache())


class TestNoOpWorktrees(unittest.TestCase):
    def test_has_repo_is_false(self):
        self.assertFalse(NoOpWorktrees().has_repo("LC-1"))

    def test_worktree_path_is_none(self):
        self.assertIsNone(NoOpWorktrees().worktree_path("LC-1"))


class TestNoOpGit(unittest.TestCase):
    def test_is_git_repo_is_false(self):
        self.assertFalse(NoOpGit().is_git_repo("/tmp/nowhere"))

    def test_has_tracked_changes_is_false(self):
        self.assertFalse(NoOpGit().has_tracked_changes("/tmp/nowhere"))

    def test_commit_tracked_raises(self):
        with self.assertRaises(GitReadError):
            NoOpGit().commit_tracked("/tmp/nowhere", "message")


class TestNoOpFs(unittest.TestCase):
    def test_iter_lines_yields_nothing(self):
        self.assertEqual(list(NoOpFs().iter_lines("/tmp/nowhere.log")), [])

    def test_log_mtime_is_none(self):
        self.assertIsNone(NoOpFs().log_mtime("/tmp/nowhere.log"))


class TestNoOpSpinPort(unittest.TestCase):
    def test_load_returns_fresh_ledger(self):
        self.assertEqual(NoOpSpinPort().load(), SpinLedger())

    def test_update_does_not_raise_and_never_accumulates(self):
        port = NoOpSpinPort()
        port.update(lambda ledger: ledger.record_death("LC-1", 1.0, None))

        self.assertEqual(port.load(), SpinLedger())


class TestNoOpStream(unittest.TestCase):
    def test_saw_terminal_command_is_false(self):
        self.assertFalse(NoOpStream().saw_terminal_command(["line"]))

    def test_saw_session_activity_is_false(self):
        self.assertFalse(NoOpStream().saw_session_activity(["line"]))
