import json

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from lightcycle.application.pool.breaker_gate import BreakerGateUseCase
from lightcycle.application.pool.tick import TickInput, TickUseCase
from tests.support.fake_store import FakeStore

scenarios("pool-wide-spin-guard.feature")

_NOW = 1000
_MAX_BOOT_SECONDS = 120
_STALL_SECONDS = 1800
_PROBE_COOLDOWN_SECONDS = 1800

_NO_WORK_LOG = (
    b"session started\n"
    b"Failed to authenticate: OAuth session expired and could not be refreshed\n"
    b"error: api_error"
)
_REAL_ACTIVITY_LOG = b'{"type":"result","subtype":"success"}'
_REJECTED = (
    '{"type":"rate_limit_event","rate_limit_info":'
    '{"status":"rejected","resetsAt":%d}}'
)


class FakeWorkers:
    def __init__(self):
        self._workers = []

    def workers_state(self):
        return self._workers

    def pid_alive(self, pid, started=None):
        return False

    def kill(self, pid):
        pass

    def mark_checked(self, spawnid):
        for w in self._workers:
            if w.get("spawnid") == spawnid:
                w["checked"] = True

    def log_mtime(self, path):
        return None

    def reap(self):
        pass

    def prune_workers(self):
        return 0


class FakeFs:
    def __init__(self):
        self.files = {}

    def read_bytes(self, path):
        return self.files.get(path)

    def iter_lines(self, path):
        content = self.files.get(path)
        if content is None:
            return
        for line in content.decode("utf-8", errors="replace").splitlines():
            yield line


class FakeBreakerPort:
    def __init__(self):
        self._state = {}

    def load(self):
        return dict(self._state)

    def save(self, state):
        self._state = dict(state)


class FakeSpinPort:
    def __init__(self):
        self._state = {}

    def load(self):
        return json.loads(json.dumps(self._state))

    def save(self, state):
        self._state = json.loads(json.dumps(state))


class FakeConfig:
    def __init__(self):
        self._spin_cap = 1
        self._max_agents = 5

    def max_boot_seconds(self):
        return _MAX_BOOT_SECONDS

    def stall_seconds(self):
        return _STALL_SECONDS

    def probe_cooldown_seconds(self):
        return _PROBE_COOLDOWN_SECONDS

    def spin_cap(self):
        return self._spin_cap

    def max_agents(self):
        return self._max_agents


class FakeSpawner:
    def __init__(self):
        self.spawned = []

    def spawn_worker(self, role):
        self.spawned.append(role)
        return {"spawnid": "x"}


def _register_dead_worker(ctx, name, step):
    ctx["dead_seq"] += 1
    spawnid = "%s-%d" % (name, ctx["dead_seq"])
    pid = ctx["dead_seq"]
    log = "/l/%s.log" % spawnid
    ctx["workers"]._workers.append(
        {"spawnid": spawnid, "pid": pid, "step": step, "log": log, "started": 0}
    )
    ctx["fs"].files[log] = _NO_WORK_LOG
    ctx["dead_logs"][name] = log
    return spawnid


def _create_two_steps_with_no_work_deaths(ctx):
    step1 = ctx["store"].create_step("build: a", step="build", role="agent")
    step2 = ctx["store"].create_step("build: b", step="build", role="agent")
    ctx["steps"] = [step1, step2]
    _register_dead_worker(ctx, "w1", step1)
    _register_dead_worker(ctx, "w2", step2)


def _run_gate(ctx):
    use_case = BreakerGateUseCase(
        ctx["workers"], ctx["fs"], ctx["breaker_port"], ctx["config"],
        spin_port=ctx["spin_port"], store=ctx["store"],
    )
    ctx["result"] = use_case.execute(now=ctx["now"])


@pytest.fixture
def ctx():
    return {}


@given(
    "a breaker gate use case backed by a breaker port, a workers port, an fs port, "
    "a spin port, and a store"
)
def _use_case(ctx):
    ctx["workers"] = FakeWorkers()
    ctx["fs"] = FakeFs()
    ctx["breaker_port"] = FakeBreakerPort()
    ctx["spin_port"] = FakeSpinPort()
    ctx["store"] = FakeStore()
    ctx["config"] = FakeConfig()
    ctx["now"] = _NOW
    ctx["dead_seq"] = 0
    ctx["dead_logs"] = {}


@given(parsers.parse("the spin cap is {cap:d}"))
def _spin_cap(ctx, cap):
    ctx["config"]._spin_cap = cap


@given("2 dead, unchecked workers, each with an assigned step, each having done no work")
def _two_dead_with_steps_no_work(ctx):
    _create_two_steps_with_no_work_deaths(ctx)


@given(
    "2 dead, unchecked workers, each with an assigned step, each having done no work, "
    "this check"
)
def _two_dead_with_steps_no_work_this_check(ctx):
    _create_two_steps_with_no_work_deaths(ctx)


@given("2 dead, unchecked workers, each with an assigned step, this check")
def _two_dead_with_steps_this_check(ctx):
    _create_two_steps_with_no_work_deaths(ctx)


@given("1 dead, unchecked worker, with an assigned step, having done no work")
def _one_dead_with_step(ctx):
    step1 = ctx["store"].create_step("build: a", step="build", role="agent")
    ctx["steps"] = [step1]
    _register_dead_worker(ctx, "w1", step1)


@given("1 dead, unchecked worker with no assigned step, having done no work")
def _one_dead_no_step(ctx):
    ctx["steps"] = []
    _register_dead_worker(ctx, "w1", None)


@given("none of them carries a rate-limit rejection")
def _none_rejected(ctx):
    pass


@given("it carries no rate-limit rejection")
def _it_not_rejected(ctx):
    pass


@given("no other dead, unchecked workers this check")
def _no_other_workers(ctx):
    pass


@given("one of them carries a rate-limit rejection")
def _one_rejected(ctx):
    log = ctx["dead_logs"]["w2"]
    ctx["fs"].files[log] = (_REJECTED % (ctx["now"] + 5000)).encode()


@given("one of them shows real session activity")
def _one_shows_real_activity(ctx):
    log = ctx["dead_logs"]["w2"]
    ctx["fs"].files[log] = _REAL_ACTIVITY_LOG


@given("the pool-wide spin guard's streak has already advanced from an earlier check")
def _streak_advanced(ctx):
    ctx["spin_port"].save({"pool": {"streak": 1, "tripped": False}})


@given("the pool-wide spin guard is open")
def _guard_open(ctx):
    ctx["spin_port"].save({"pool": {"streak": ctx["config"].spin_cap(), "tripped": True}})


@given("the pool has more than one free slot")
def _free_slots(ctx):
    ctx["store"].create_step("build: r1", step="build", role="agent")
    ctx["store"].create_step("build: r2", step="build", role="agent")
    ctx["store"].create_step("build: r3", step="build", role="agent")


@when("the pool's breaker gate runs")
def _gate_runs(ctx):
    _run_gate(ctx)


@when("a later check observes real session activity among the dead-with-step workers")
def _later_check_real_activity(ctx):
    step1 = ctx["store"].create_step("build: later", step="build", role="agent")
    _register_dead_worker(ctx, "later", step1)
    ctx["fs"].files[ctx["dead_logs"]["later"]] = _REAL_ACTIVITY_LOG
    _run_gate(ctx)


@when("the pool ticks")
def _pool_ticks(ctx):
    breaker_gate = BreakerGateUseCase(
        ctx["workers"], ctx["fs"], ctx["breaker_port"], ctx["config"],
        spin_port=ctx["spin_port"], store=ctx["store"],
    )
    spawner = FakeSpawner()
    tick = TickUseCase(
        ctx["store"], ctx["workers"], spawner, ctx["config"], breaker_gate=breaker_gate,
        spin_port=ctx["spin_port"],
    )
    ctx["tick_result"] = tick.execute(TickInput(now=ctx["now"]))
    ctx["spawner"] = spawner


@then("the pool-wide spin guard opens")
def _opens(ctx):
    assert ctx["result"].spin_open is True
    assert ctx["result"].spin_opened is True


@then("the pool-wide spin guard stays closed")
def _stays_closed(ctx):
    assert ctx["result"].spin_open is False


@then(
    "a step is parked for a human, its observation naming the pattern as pool-wide, "
    "not step-specific"
)
def _parked_pool_wide(ctx):
    parked = [s for s in ctx["steps"] if ctx["store"].get_node(s).role == "human"]
    assert len(parked) == 1
    reason = ctx["store"].get_node(parked[0]).park.reason or ""
    assert "pool-wide" in reason


@then("the pool-wide spin guard's streak resets")
def _streak_resets(ctx):
    assert ctx["spin_port"].load()["pool"]["streak"] == 0


@then("the pool-wide spin guard closes on that same check")
def _closes_same_check(ctx):
    assert ctx["result"].spin_open is False


@then("no more than 1 worker is spawned")
def _no_more_than_one_spawned(ctx):
    assert len(ctx["spawner"].spawned) <= 1
