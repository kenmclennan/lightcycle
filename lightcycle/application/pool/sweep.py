from dataclasses import dataclass, field
from typing import List

from lightcycle.application.flow.park_step import ParkInput, ParkStepUseCase
from lightcycle.domain.pool import WorkerPool
from lightcycle.ports.git import GitReadError
from lightcycle.ports.workers import RegistryUnreadable


@dataclass(frozen=True)
class SweepResponse:
    swept: List[str]
    killed: List[str]
    pruned: int
    preserved: List[str] = field(default_factory=list)
    capture_failed: List[str] = field(default_factory=list)
    parked: List[str] = field(default_factory=list)
    not_checked: List[str] = field(default_factory=list)


class SweepUseCase:
    def __init__(self, store, workers, worktrees, git, fs, spin_port, spin_cap, stream):
        self._store = store
        self._workers = workers
        self._worktrees = worktrees
        self._git = git
        self._fs = fs
        self._spin_port = spin_port
        self._spin_cap = spin_cap
        self._stream = stream

    def _capture(self, t):
        item = t.item or t.id
        if not self._worktrees.has_repo(item):
            return "not_checked"
        path = self._worktrees.worktree_path(item)
        if not self._git.is_git_repo(path):
            return "not_checked"
        try:
            dirty = self._git.has_tracked_changes(path)
        except GitReadError:
            return False
        if not dirty:
            return None
        message = "wip: preserved %s on reclaim" % t.id
        return self._git.commit_tracked(path, message)

    def _saw_terminal_command(self, log):
        return self._stream.saw_terminal_command(self._fs.iter_lines(log))

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
        if not no_work:
            self._spin_port.update(lambda ledger: ledger.record_activity(step_id))
            return False
        parked_entry = []

        def _mutate(ledger):
            ledger = ledger.record_death(step_id, now, last_line)
            if ledger.should_park(step_id, self._spin_cap):
                parked_entry.append(ledger.entry(step_id))
                return ledger.clear(step_id)
            return ledger

        self._spin_port.update(_mutate)
        if parked_entry:
            entry = parked_entry[0]
            self._park_for_spin(step_id, entry.count, entry.since, now, last_line)
            return True
        return False

    def execute(self, now, max_boot, stall_seconds) -> SweepResponse:
        probe = self._workers.pid_alive
        try:
            pool = WorkerPool(self._workers.workers_state())
        except RegistryUnreadable:
            return SweepResponse(swept=[], killed=[], pruned=0)
        claimed = self._store.claimed_steps()
        claimed_ids = {t.id for t in claimed}
        covered = pool.covered_steps(probe)
        live_spawnids = pool.live_spawnids(probe)
        booting = pool.any_booting(probe, now, max_boot)
        stalled = [
            w
            for w in pool.stalled(probe, now, max_boot, stall_seconds, self._fs.log_mtime)
            if not self._saw_terminal_command(w.log)
        ]
        stalled_ids = {w.step for w in stalled}
        for w in stalled:
            self._workers.kill(w.pid)
            self._workers.mark_checked(w.spawnid)
        swept = []
        preserved = []
        capture_failed = []
        not_checked = []
        parked = []
        for t in claimed:
            if t.id not in stalled_ids and (
                t.id in covered or (t.claimed_by and t.claimed_by in live_spawnids) or booting
            ):
                continue
            captured = self._capture(t)
            if captured is True:
                preserved.append(t.id)
            elif captured is False:
                capture_failed.append(t.id)
            elif captured == "not_checked":
                not_checked.append(t.id)
            if t.id not in stalled_ids:
                dead = pool.dead_for_step(probe, t.id)
                if dead is not None:
                    lines = list(self._fs.iter_lines(dead.log))
                    no_work = not self._stream.saw_session_activity(lines)
                    last_line = self._last_nonempty_line(lines)
                    if self._advance_spin(t.id, now, no_work, last_line):
                        parked.append(t.id)
                        continue
            self._store.reclaim(t.id)
            swept.append(t.id)
        orphans = pool.orphans(probe, now, max_boot, claimed_ids)
        for w in orphans:
            self._workers.kill(w.pid)
        try:
            pruned = self._workers.prune_workers()
        except RegistryUnreadable:
            pruned = 0
        return SweepResponse(
            swept=swept,
            killed=[w.spawnid for w in orphans] + [w.spawnid for w in stalled],
            pruned=pruned,
            preserved=preserved,
            capture_failed=capture_failed,
            parked=parked,
            not_checked=not_checked,
        )
