from lightcycle.application.pool.backup import BackupResponse
from lightcycle.application.pool.breaker_gate import BreakerGateResponse
from lightcycle.application.pool.hook_completions import HookCompletionsResponse
from lightcycle.application.pool.monitor_prs import MonitorPrsResponse
from lightcycle.application.pool.retro_cadence import RetroCadenceResponse
from lightcycle.domain.pool import Breaker
from lightcycle.domain.pool.spin_ledger import SpinLedger
from lightcycle.ports.git import GitReadError


class NoOpMonitor:
    def execute(self):
        return MonitorPrsResponse(merged=[])


class NoOpCadenceGate:
    def execute(self, now):
        return RetroCadenceResponse()


class NoOpBreakerGate:
    def execute(self, now):
        return BreakerGateResponse(breaker=Breaker())


class NoOpHookCompletions:
    def execute(self, since):
        return HookCompletionsResponse()


class NoOpBackupGate:
    def execute(self, now):
        return BackupResponse()


class NoOpUsageGate:
    def execute(self, now):
        return None


class NoOpFlowService:
    def clear_cache(self):
        return None


class NoOpWorktrees:
    def has_repo(self, item):
        return False

    def worktree_path(self, item):
        return None


class NoOpGit:
    def is_git_repo(self, path):
        return False

    def has_tracked_changes(self, path):
        return False

    def commit_tracked(self, path, message):
        raise GitReadError("NoOpGit cannot commit: %s" % path)


class NoOpFs:
    def iter_lines(self, log):
        return iter(())

    def log_mtime(self, path):
        return None


class NoOpSpinPort:
    def load(self):
        return SpinLedger()

    def update(self, mutate):
        mutate(SpinLedger())


class NoOpStream:
    def saw_terminal_command(self, lines):
        return False

    def saw_session_activity(self, lines):
        return False
