from dataclasses import dataclass, field
from typing import List

from lightcycle.application.flow.park_step import ParkInput, ParkStepUseCase
from lightcycle.domain.pool import WorkerPool
from lightcycle.domain.pool.worker_session import saw_session_activity, saw_terminal_command
from lightcycle.ports.git import GitReadError


@dataclass(frozen=True)
class SweepResponse:
    swept: List[str]
    killed: List[str]
    pruned: int
    preserved: List[str] = field(default_factory=list)
    capture_failed: List[str] = field(default_factory=list)
    parked: List[str] = field(default_factory=list)


class SweepUseCase:
    def __init__(
        self, store, workers, worktrees=None, git=None, fs=None, spin_port=None, spin_cap=None
    ):
        self._store = store
        self._workers = workers
        self._worktrees = worktrees
        self._git = git
        self._fs = fs
        self._spin_port = spin_port
        self._spin_cap = spin_cap

    def _capture(self, t):
        if self._worktrees is None or self._git is None:
            return None
        item = t.parent or t.id
        if not self._worktrees.has_repo(item):
            return None
        path = self._worktrees.worktree_path(item)
        if not self._git.is_git_repo(path):
            return None
        try:
            dirty = self._git.has_uncommitted(path)
        except GitReadError:
            return False
        if not dirty:
            return None
        message = "wip: preserved %s on reclaim" % t.id
        return self._git.commit_all(path, message)

    def _saw_terminal_command(self, log):
        if self._fs is None:
            return False
        return saw_terminal_command(self._fs.iter_lines(log))

    def _last_nonempty_line(self, lines):
        last = None
        for line in lines:
            stripped = line.strip()
            if stripped:
                last = stripped
        return last

    def _park_for_spin(self, step_id, count, since, now, last_line):
        elapsed = int(now - since)
        observation = (
            "This step's worker died %d times in a row with no observed model activity "
            "(no `assistant` or `result` event in its log), spanning ~%ds since the first "
            "death. The most recent worker's log ended with: %s"
            % (count, elapsed, last_line if last_line else "(empty)")
        )
        decision = (
            "Confirm the pool can actually reach the model (auth, network, or model access) "
            "before unblocking - unblocking without fixing the underlying cause will spin "
            "the same way again."
        )
        tried = (
            "%d automatic re-spawns, each exiting immediately with no session activity." % count
        )
        ParkStepUseCase(self._store).execute(
            ParkInput(step=step_id, observation=observation, decision=decision, tried=tried)
        )

    def _advance_spin(self, step_id, now, no_work, last_line):
        state = self._spin_port.load()
        steps = dict(state.get("steps") or {})
        if not no_work:
            if step_id in steps:
                del steps[step_id]
                state["steps"] = steps
                self._spin_port.save(state)
            return False
        entry = steps.get(step_id) or {}
        count = entry.get("count", 0) + 1
        since = entry.get("since", now)
        if count >= self._spin_cap:
            del steps[step_id]
            state["steps"] = steps
            self._spin_port.save(state)
            self._park_for_spin(step_id, count, since, now, last_line)
            return True
        steps[step_id] = {"count": count, "since": since, "last_line": last_line}
        state["steps"] = steps
        self._spin_port.save(state)
        return False

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
        parked = []
        for t in claimed:
            if t.id not in stalled_ids and (t.id in covered or booting):
                continue
            captured = self._capture(t)
            if captured is True:
                preserved.append(t.id)
            elif captured is False:
                capture_failed.append(t.id)
            if t.id not in stalled_ids and self._spin_port is not None and self._spin_cap is not None:
                dead = pool.dead_for_step(probe, t.id)
                if dead is not None and self._fs is not None:
                    lines = list(self._fs.iter_lines(dead.log))
                    no_work = not saw_session_activity(lines)
                    last_line = self._last_nonempty_line(lines)
                    if self._advance_spin(t.id, now, no_work, last_line):
                        parked.append(t.id)
                        continue
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
            parked=parked,
        )
