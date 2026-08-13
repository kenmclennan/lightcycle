import json

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from lightcycle.application.pool.breaker_gate import BreakerGateUseCase
from lightcycle.domain.pool import Breaker

scenarios("breaker-probe-stall-recovery.feature")

_NOW = 1000
_STALL_SECONDS = 1800
_PROBE_COOLDOWN_SECONDS = 1800
_MAX_BOOT_SECONDS = 120

_REJECTED = (
    '{"type":"rate_limit_event","rate_limit_info":'
    '{"status":"rejected","resetsAt":%d}}'
)
_NO_REJECTION = '{"type":"result","subtype":"success"}'
_TERMINAL_MARKER = json.dumps(
    {
        "type": "assistant",
        "message": {
            "content": [{"type": "tool_use", "input": {"command": "lc done t done"}}]
        },
    }
)


class FakeWorkers:
    def __init__(self):
        self._workers = []
        self._alive = set()
        self._log_mtimes = {}
        self.killed = []
        self.checked = []

    def add(self, spawnid, pid, alive, mtime=None):
        self._workers.append(
            {"spawnid": spawnid, "pid": pid, "step": "probe", "started": 0,
             "log": "/l/%s.log" % spawnid}
        )
        if alive:
            self._alive.add(pid)
        if mtime is not None:
            self._log_mtimes["/l/%s.log" % spawnid] = mtime

    def workers_state(self):
        return self._workers

    def pid_alive(self, pid, started=None):
        return pid in self._alive

    def reap(self):
        pass

    def kill(self, pid):
        self.killed.append(pid)

    def mark_checked(self, spawnid):
        self.checked.append(spawnid)
        for w in self._workers:
            if w.get("spawnid") == spawnid:
                w["checked"] = True

    def log_mtime(self, path):
        return self._log_mtimes.get(path)


class FakeFs:
    def __init__(self):
        self._files = {}

    def set_file(self, spawnid, content):
        self._files["/l/%s.log" % spawnid] = content.encode()

    def read_bytes(self, path):
        return self._files.get(path)


class FakeBreakerPort:
    def __init__(self):
        self._state = {}

    def load(self):
        return dict(self._state)

    def save(self, state):
        self._state = dict(state)


class FakeConfig:
    def max_boot_seconds(self):
        return _MAX_BOOT_SECONDS

    def stall_seconds(self):
        return _STALL_SECONDS

    def probe_cooldown_seconds(self):
        return _PROBE_COOLDOWN_SECONDS


@pytest.fixture
def ctx():
    return {}


@given("a breaker gate use case backed by a breaker port, a workers port, and an fs port")
def _use_case(ctx):
    ctx["workers"] = FakeWorkers()
    ctx["fs"] = FakeFs()
    ctx["breaker_port"] = FakeBreakerPort()
    ctx["config"] = FakeConfig()
    ctx["now"] = _NOW
    ctx["spawnids"] = {}


def _set_breaker_state(ctx, is_open, reset_at):
    ctx["breaker_port"].save({"open": is_open, "reset_at": reset_at})
    ctx["reset_at_loaded"] = reset_at


@given("the breaker is open and past its reset time")
def _open_past_reset(ctx):
    _set_breaker_state(ctx, True, ctx["now"] - 500)


@given(parsers.re(r"^the breaker's state is (?P<breaker_state>.+)$"))
def _breaker_state(ctx, breaker_state):
    if breaker_state == "closed":
        _set_breaker_state(ctx, False, None)
    elif breaker_state == "open but not yet past its reset time":
        _set_breaker_state(ctx, True, ctx["now"] + 500)
    elif breaker_state == "open and past its reset time":
        _set_breaker_state(ctx, True, ctx["now"] - 500)
    else:
        raise ValueError("unknown breaker state %r" % breaker_state)


def _add_worker(ctx, name, alive, mtime=None):
    pid = len(ctx["spawnids"]) + 1
    ctx["spawnids"][name] = "%s-sp" % name
    ctx["workers"].add(ctx["spawnids"][name], pid, alive, mtime=mtime)
    return ctx["spawnids"][name]


@given("the probe worker is alive and its log has stalled")
def _probe_stalled(ctx):
    _add_worker(ctx, "probe", alive=True, mtime=ctx["now"] - _STALL_SECONDS - 1)


@given("an alive worker's log has stalled")
def _alive_worker_stalled(ctx):
    _add_worker(ctx, "probe", alive=True, mtime=ctx["now"] - _STALL_SECONDS - 1)


@given("the probe worker is alive and its log grew within the stall threshold")
def _probe_within_threshold(ctx):
    _add_worker(ctx, "probe", alive=True, mtime=ctx["now"] - _STALL_SECONDS + 1)


@given("the probe worker's log shows a terminal marker")
def _probe_terminal_marker(ctx):
    ctx["fs"].set_file(ctx["spawnids"]["probe"], _TERMINAL_MARKER)


@given("a different worker is dead, unchecked, and its log carries a rate-limit rejection")
def _dead_rejected_worker(ctx):
    spawnid = _add_worker(ctx, "rejected", alive=False)
    ctx["rejection_reset_at"] = ctx["now"] + 5000
    ctx["fs"].set_file(spawnid, _REJECTED % ctx["rejection_reset_at"])


@given("the probe worker is dead, unchecked, and its log carries no rejection")
def _probe_dead_no_rejection(ctx):
    spawnid = _add_worker(ctx, "probe", alive=False)
    ctx["fs"].set_file(spawnid, _NO_REJECTION)


@given("the probe worker is dead, unchecked, and its log carries a rate-limit rejection")
def _probe_dead_rejected(ctx):
    spawnid = _add_worker(ctx, "probe", alive=False)
    ctx["rejection_reset_at"] = ctx["now"] + 5000
    ctx["fs"].set_file(spawnid, _REJECTED % ctx["rejection_reset_at"])


@given("the breaker's reset time was re-armed by a probe cooldown")
def _already_rearmed(ctx):
    _set_breaker_state(ctx, True, ctx["now"] + _PROBE_COOLDOWN_SECONDS)


@given("no worker is alive")
def _no_worker_alive(ctx):
    pass


@when("the pool's breaker gate runs")
def _run_gate(ctx):
    use_case = BreakerGateUseCase(ctx["workers"], ctx["fs"], ctx["breaker_port"], ctx["config"])
    ctx["result"] = use_case.execute(now=ctx["now"])


@when("the re-armed reset time has passed")
def _reset_time_passed(ctx):
    state = Breaker.from_state(ctx["breaker_port"].load())
    ctx["now"] = state.reset_at + 1
    ctx["breaker_after_wait"] = state


@then("the breaker does not close")
def _does_not_close(ctx):
    assert ctx["result"].closed is False
    assert ctx["result"].breaker.is_open is True


@then("the breaker does not treat the stall as a successful probe")
def _not_a_success(ctx):
    assert ctx["result"].closed is False
    assert ctx["workers"].checked == []


@then("the breaker stays open")
def _stays_open(ctx):
    assert ctx["result"].breaker.is_open is True


@then("the reset time is re-armed to now plus the probe cooldown")
def _rearmed_to_cooldown(ctx):
    assert ctx["result"].rearmed is True
    assert ctx["result"].breaker.reset_at == ctx["now"] + _PROBE_COOLDOWN_SECONDS


@then("the reset time is unchanged from the state that was loaded")
def _unchanged(ctx):
    assert ctx["result"].breaker.reset_at == ctx["reset_at_loaded"]


@then(parsers.re(r"^the reset time is (?P<verdict>not re-armed|re-armed)$"))
def _rearm_verdict(ctx, verdict):
    assert ctx["result"].rearmed is (verdict == "re-armed")


@then("the breaker opens with the rejection's reset time")
def _opens_with_rejection(ctx):
    assert ctx["result"].opened is True
    assert ctx["result"].breaker.reset_at == ctx["rejection_reset_at"]


@then("the breaker closes")
def _closes(ctx):
    assert ctx["result"].closed is True
    assert ctx["result"].breaker.is_open is False


@then("the breaker allows a fresh probe to spawn")
def _allows_fresh_probe(ctx):
    state = Breaker.from_state(ctx["breaker_port"].load())
    assert state.spawn_cap(ctx["now"], alive_count=0) == 1
