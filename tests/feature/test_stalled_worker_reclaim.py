import json

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from lightcycle.application.pool.sweep import SweepUseCase
from tests.support.fake_store import FakeStore

scenarios("stalled-worker-reclaim.feature")

NOW = 1_000_000.0
MAX_BOOT = 120
STALL_SECONDS = 1800

NON_TERMINAL_LOG = json.dumps(
    {"type": "assistant", "message": {"content": [{"type": "tool_use", "input": {"command": "echo hi"}}]}}
).encode()

TERMINAL_LOG = json.dumps(
    {
        "type": "assistant",
        "message": {"content": [{"type": "tool_use", "input": {"command": "lc done t done"}}]},
    }
).encode()


class FakeWorkers:
    def __init__(self):
        self._workers = []
        self._alive = set()
        self._log_mtimes = {}
        self.killed = []
        self.checked = []

    def register(self, entry, alive=True):
        self._workers.append(entry)
        if alive:
            self._alive.add(entry["pid"])

    def set_log_mtime(self, log, mtime):
        self._log_mtimes[log] = mtime

    def workers_state(self):
        return self._workers

    def pid_alive(self, pid, started=None):
        return pid in self._alive

    def kill(self, pid):
        self.killed.append(pid)
        self._alive.discard(pid)

    def prune_workers(self):
        return 0

    def mark_checked(self, spawnid):
        self.checked.append(spawnid)

    def log_mtime(self, path):
        return self._log_mtimes.get(path)


class FakeFs:
    def __init__(self):
        self.files = {}

    def read_bytes(self, path):
        return self.files.get(path)


class FakeWorktrees:
    def __init__(self):
        self.has_repo_result = True
        self.paths = {}

    def has_repo(self, item):
        return self.has_repo_result

    def worktree_path(self, item):
        return self.paths.get(item, "/worktrees/%s" % item)


class FakeGit:
    def __init__(self, events):
        self.dirty = set()
        self.commits = []
        self._events = events

    def is_git_repo(self, root):
        return True

    def has_uncommitted(self, root):
        return root in self.dirty

    def commit_all(self, root, message):
        self.commits.append((root, message))
        self._events.append(("commit", root))
        return True


class TrackingStore(FakeStore):
    def __init__(self, events):
        super().__init__()
        self._events = events

    def reclaim(self, tid):
        self._events.append(("reclaim", tid))
        return super().reclaim(tid)


@pytest.fixture
def ctx():
    events = []
    return {
        "now": NOW,
        "spawnid": "sp-1",
        "pid": 4242,
        "log": "/logs/sp-1.log",
        "store": TrackingStore(events),
        "workers": FakeWorkers(),
        "fs": FakeFs(),
        "worktrees": FakeWorktrees(),
        "git": FakeGit(events),
        "events": events,
    }


def _run_sweep(ctx):
    use_case = SweepUseCase(
        ctx["store"], ctx["workers"], worktrees=ctx["worktrees"], git=ctx["git"], fs=ctx["fs"]
    )
    ctx["result"] = use_case.execute(ctx["now"], MAX_BOOT, STALL_SECONDS)


@given("a worker has claimed a step")
def _claimed(ctx):
    item = ctx["store"].create_item("feature", theme=ctx["store"].create_theme("theme"))
    step = ctx["store"].create_step("build: feature", step="build", role="coder", parent=item)
    ctx["store"].update_state(step, "in_progress")
    ctx["store"].assign(step, ctx["spawnid"])
    ctx["item"] = item
    ctx["step"] = step
    entry = {
        "spawnid": ctx["spawnid"],
        "pid": ctx["pid"],
        "step": step,
        "started": ctx["now"] - MAX_BOOT - 1,
        "log": ctx["log"],
    }
    ctx["worker_entry"] = entry
    ctx["workers"].register(entry)


@given("a worker has not yet claimed a step")
def _not_claimed(ctx):
    entry = {
        "spawnid": ctx["spawnid"],
        "pid": ctx["pid"],
        "step": None,
        "started": ctx["now"],
        "log": ctx["log"],
    }
    ctx["worker_entry"] = entry
    ctx["workers"].register(entry)


@given("the worker is past its boot window")
def _past_boot(ctx):
    ctx["worker_entry"]["started"] = ctx["now"] - MAX_BOOT - 1


@given("the worker is still inside its boot window")
def _inside_boot(ctx):
    ctx["worker_entry"]["started"] = ctx["now"] - 1


@given("the worker's log last grew more than the stall threshold ago")
def _log_stale(ctx):
    ctx["workers"].set_log_mtime(ctx["log"], ctx["now"] - STALL_SECONDS - 1)


@given("the worker's log last grew within the stall threshold")
def _log_fresh(ctx):
    ctx["workers"].set_log_mtime(ctx["log"], ctx["now"] - STALL_SECONDS + 1)


@given("the worker's log contains no terminal marker")
def _no_terminal_marker(ctx):
    ctx["fs"].files[ctx["log"]] = NON_TERMINAL_LOG


@given("the worker's log contains a terminal marker")
def _terminal_marker(ctx):
    ctx["fs"].files[ctx["log"]] = TERMINAL_LOG


@given("the worker's log stopped growing well before a multi-hour suspend")
def _log_stopped_before_suspend(ctx):
    ctx["workers"].set_log_mtime(ctx["log"], ctx["now"] - 60)


@given("the wall clock then advances by several hours across the suspend")
def _advance_clock(ctx):
    ctx["now"] += 10 * 3600


@given("the step's worktree has uncommitted changes")
def _dirty_worktree(ctx):
    path = ctx["worktrees"].worktree_path(ctx["item"])
    ctx["git"].dirty.add(path)


@when("the pool sweeps")
def _sweep(ctx):
    _run_sweep(ctx)


@when("the pool sweeps after the resume")
def _sweep_after_resume(ctx):
    _run_sweep(ctx)


@then(parsers.parse("the worker is {verdict} as stalled"))
def _verdict(ctx, verdict):
    if verdict == "identified":
        assert ctx["pid"] in ctx["workers"].killed
    else:
        assert ctx["pid"] not in ctx["workers"].killed


@then("the worker is killed")
def _killed(ctx):
    assert ctx["pid"] in ctx["workers"].killed
    assert ctx["spawnid"] in ctx["result"].killed


@then("the worker's record is marked checked")
def _marked_checked(ctx):
    assert ctx["spawnid"] in ctx["workers"].checked


@then("the step is reclaimed to ready")
def _reclaimed(ctx):
    assert ctx["step"] in ctx["result"].swept
    assert ctx["store"].get_node(ctx["step"]).state == "ready"


@then("the worker is not treated as though it just started")
def _not_freshly_started(ctx):
    assert (ctx["now"] - ctx["worker_entry"]["started"]) > MAX_BOOT
    assert ctx["pid"] in ctx["workers"].killed


@then("the uncommitted changes are committed before the step is reclaimed to ready")
def _committed_before_reclaim(ctx):
    committed_roots = [root for root, _ in ctx["git"].commits]
    assert ctx["worktrees"].worktree_path(ctx["item"]) in committed_roots
    kinds = [e[0] for e in ctx["events"]]
    assert kinds.index("commit") < kinds.index("reclaim")
    assert ctx["store"].get_node(ctx["step"]).state == "ready"
