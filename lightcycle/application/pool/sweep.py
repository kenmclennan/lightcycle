import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from lightcycle.application.flow.park_step import ParkInput, ParkStepUseCase
from lightcycle.domain.pool import WorkerPool
from lightcycle.ports.git import GitReadError
from lightcycle.ports.workers import RegistryUnreadable


@dataclass(frozen=True)
class SweepEnd:
    reason: str
    session: Optional[int]


@dataclass(frozen=True)
class SweepResponse:
    swept: List[str]
    killed: List[str]
    pruned: int
    preserved: List[str] = field(default_factory=list)
    capture_failed: List[str] = field(default_factory=list)
    parked: List[str] = field(default_factory=list)
    not_checked: List[str] = field(default_factory=list)
    ended: Dict[str, SweepEnd] = field(default_factory=dict)


def sweep_end_suffix(response, step_id):
    end = response.ended.get(step_id)
    if end is None:
        return ""
    prefix = "session %d " % end.session if end.session is not None else ""
    return "  (%sended: %s)" % (prefix, end.reason)


class SweepUseCase:
    def __init__(self, store, workers, worktrees, git, worker_log, spin_port, spin_cap, stream):
        self._store = store
        self._workers = workers
        self._worktrees = worktrees
        self._git = git
        self._worker_log = worker_log
        self._spin_port = spin_port
        self._spin_cap = spin_cap
        self._stream = stream

    def _capture(self, t):
        item = t.item or t.id
        if not self._worktrees.has_repo(item):
            return "not_checked"
        path = self._worktrees.worktree_path(t)
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

    def _park_for_exits(self, step_id, count, since, now, last_line):
        elapsed = int(now - since)
        observation = (
            "This step's worker ended %d times after real work without closing the step, "
            "spanning ~%ds since the first. The most recent worker's log ended with: %s"
            % (count, elapsed, last_line if last_line else "(empty)")
        )
        decision = (
            "A human must read the worker log and decide. If the step is held, say so and "
            "run `lc release %s`; otherwise unblock it once the cause is understood. A "
            "step killed repeatedly mid-session (for example by pool restarts) parks here too."
            % step_id
        )
        tried = "%d automatic re-dispatches, each ending with no outcome." % count
        ParkStepUseCase(self._store).execute(
            ParkInput(step=step_id, observation=observation, decision=decision, tried=tried)
        )

    def _advance_spin(self, step_id, now, no_work, last_line, spawnid):
        if not no_work:
            exit_entry = []

            def _record(ledger):
                ledger = ledger.record_activity(step_id).record_exit(
                    step_id, now, last_line, spawnid)
                if ledger.should_park_exit(step_id, self._spin_cap):
                    exit_entry.append(ledger.exits[step_id])
                    return ledger.clear(step_id)
                return ledger

            self._spin_port.update(_record)
            if exit_entry:
                entry = exit_entry[0]
                self._park_for_exits(step_id, entry.count, entry.since, now, last_line)
                return True
            return False
        parked_entry = []

        def _mutate(ledger):
            ledger = ledger.record_death(step_id, now, last_line, spawnid)
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

    def _prune_exits(self):
        def _drop(ledger):
            keep = set()
            for step_id in ledger.exits:
                try:
                    if self._store.get_node(step_id).state != "done":
                        keep.add(step_id)
                except KeyError:
                    pass
            return ledger.drop_exits(keep)

        self._spin_port.update(_drop)

    def execute(self, now, max_boot, stall_seconds, sleeps=()) -> SweepResponse:
        probe = self._workers.pid_alive
        try:
            pool = WorkerPool(self._workers.workers_state())
        except RegistryUnreadable:
            return SweepResponse(swept=[], killed=[], pruned=0)
        claimed = self._store.claimed_steps()
        claimed_ids = {t.id for t in claimed}
        claimed_owner = {t.id: t.claimed_by for t in claimed}
        pre_claim_dead = pool.dead_steps_outside(probe, claimed_ids)
        covered = pool.covered_steps(probe)
        live_spawnids = pool.live_spawnids(probe)
        booting = pool.any_booting(probe, now, max_boot, sleeps)
        stalled = [
            w
            for w in pool.stalled(
                probe, now, max_boot, stall_seconds,
                lambda path: self._worker_log.log_mtime(path), sleeps,
            )
            if claimed_owner.get(w.step) == w.spawnid
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
        ended = {}
        for t in claimed:
            if t.id not in stalled_ids and (
                t.id in covered or t.claimed_by in live_spawnids or booting
            ):
                continue
            captured = self._capture(t)
            if captured is True:
                preserved.append(t.id)
            elif captured is False:
                capture_failed.append(t.id)
                sys.stderr.write(
                    "warning: could not preserve work on %s at reclaim; "
                    "reclaiming without a wip commit\n" % t.id
                )
            elif captured == "not_checked":
                not_checked.append(t.id)
            dead = None if t.id in stalled_ids else pool.dead_for_step(probe, t.id)
            if t.id in stalled_ids:
                reason = "stalled"
            elif dead is None:
                reason = "reclaimed"
            else:
                reason = "pool-stopped" if dead.halted else "died"
            ended[t.id] = SweepEnd(reason, self._store.end_session(t.id, reason))
            if t.id not in stalled_ids:
                if dead is not None:
                    lines = list(self._worker_log.iter_lines(dead.log))
                    no_work = not self._stream.saw_session_activity(lines)
                    last_line = self._last_nonempty_line(lines)
                    if self._advance_spin(t.id, now, no_work, last_line, dead.spawnid):
                        parked.append(t.id)
                        continue
            self._store.reclaim(t.id)
            swept.append(t.id)
        for step_id in pre_claim_dead:
            dead = pool.dead_for_step(probe, step_id)
            if dead is None or dead.halted:
                continue
            lines = list(self._worker_log.iter_lines(dead.log))
            no_work = not self._stream.saw_session_activity(lines)
            last_line = self._last_nonempty_line(lines)
            if self._advance_spin(step_id, now, no_work, last_line, dead.spawnid):
                parked.append(step_id)
        self._prune_exits()
        orphans = pool.orphans(probe, now, max_boot, claimed_owner, sleeps)
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
            ended=ended,
        )
