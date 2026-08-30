from dataclasses import dataclass, field
from typing import List

from lightcycle.domain.pool import WorkerPool
from lightcycle.domain.pool.worker_session import saw_terminal_command


@dataclass(frozen=True)
class SweepResponse:
    swept: List[str]
    killed: List[str]
    pruned: int
    preserved: List[str] = field(default_factory=list)
    capture_failed: List[str] = field(default_factory=list)


class SweepUseCase:
    def __init__(self, store, workers, worktrees=None, git=None, fs=None):
        self._store = store
        self._workers = workers
        self._worktrees = worktrees
        self._git = git
        self._fs = fs

    def _capture(self, t):
        if self._worktrees is None or self._git is None:
            return None
        item = t.parent or t.id
        if not self._worktrees.has_repo(item):
            return None
        path = self._worktrees.worktree_path(item)
        if not self._git.is_git_repo(path):
            return None
        if not self._git.has_uncommitted(path):
            return None
        message = "wip: preserved %s on reclaim" % t.id
        return self._git.commit_all(path, message)

    def _saw_terminal_command(self, log):
        if self._fs is None:
            return False
        return saw_terminal_command(self._fs.iter_lines(log))

    def execute(self, now, max_boot, stall_seconds) -> SweepResponse:
        probe = self._workers.pid_alive
        pool = WorkerPool.from_state(self._workers.workers_state())
        claimed = self._store.claimed_steps()
        claimed_ids = {t.id for t in claimed}
        covered = pool.covered_steps(probe)
        booting = pool.any_booting(probe, now, max_boot)
        stalled = [
            w
            for w in pool.stalled(probe, now, max_boot, stall_seconds, self._workers.log_mtime)
            if not self._saw_terminal_command(w.log)
        ]
        stalled_ids = {w.step for w in stalled}
        for w in stalled:
            self._workers.kill(w.pid)
            self._workers.mark_checked(w.spawnid)
        swept = []
        preserved = []
        capture_failed = []
        for t in claimed:
            if t.id not in stalled_ids and (t.id in covered or booting):
                continue
            captured = self._capture(t)
            if captured is True:
                preserved.append(t.id)
            elif captured is False:
                capture_failed.append(t.id)
            self._store.reclaim(t.id)
            swept.append(t.id)
        orphans = pool.orphans(probe, now, max_boot, claimed_ids)
        for w in orphans:
            self._workers.kill(w.pid)
        return SweepResponse(
            swept=swept,
            killed=[w.spawnid for w in orphans] + [w.spawnid for w in stalled],
            pruned=self._workers.prune_workers(),
            preserved=preserved,
            capture_failed=capture_failed,
        )
