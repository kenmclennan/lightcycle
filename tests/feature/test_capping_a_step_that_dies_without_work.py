import json

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from lightcycle.application.flow.park_step import ParkInput, ParkStepUseCase
from lightcycle.application.flow.unblock_step import UnblockInput, UnblockStepUseCase
from lightcycle.application.pool.sweep import SweepUseCase
from lightcycle.application.services.flow import FlowService
from lightcycle.domain.pool.worker_session import saw_session_activity
from tests.support.fake_fs import FakeFs as FlowFakeFs
from tests.support.fake_store import FakeStore

scenarios("capping-a-step-that-dies-without-work.feature")

NOW = 1_000_000.0
MAX_BOOT = 120
STALL_SECONDS = 1800

_ASSISTANT_LOG = json.dumps({"type": "assistant", "message": {"content": []}})
_RESULT_LOG = json.dumps({"type": "result", "subtype": "success"})
_RATE_LIMIT_LOG = json.dumps(
    {"type": "rate_limit_event", "rate_limit_info": {"status": "rejected", "resetsAt": 500}}
)
_PLAIN_TEXT_LOG = (
    "session started\n"
    "Failed to authenticate: OAuth session expired and could not be refreshed\n"
    "error: api_error"
)

_LOG_CONTENT_BY_DESCRIPTION = {
    "an assistant event": _ASSISTANT_LOG,
    "a result event": _RESULT_LOG,
    "only a rate-limit rejection event": _RATE_LIMIT_LOG,
    "no lines at all": "",
    "only plain, non-JSON diagnostic text": _PLAIN_TEXT_LOG,
}

_NO_WORK_LOG = _PLAIN_TEXT_LOG.encode()
_REAL_ACTIVITY_LOG = _RESULT_LOG.encode()


class FakeWorkers:
    def __init__(self):
        self._workers = []
        self._alive = set()
        self.killed = []
        self.checked = []

    def register(self, entry, alive=True):
        self._workers.append(entry)
        if alive:
            self._alive.add(entry["pid"])

    def kill_worker(self, pid):
        self._alive.discard(pid)

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
        return getattr(self, "_log_mtimes", {}).get(path)


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


class FakeSpinPort:
    def __init__(self, state=None):
        self._state = state or {}

    def load(self):
        return json.loads(json.dumps(self._state))

    def save(self, state):
        self._state = json.loads(json.dumps(state))


def _run_sweep(ctx):
    use_case = SweepUseCase(
        ctx["store"], ctx["workers"], fs=ctx["fs"],
        spin_port=ctx["spin_port"], spin_cap=ctx["spin_cap"],
    )
    ctx["result"] = use_case.execute(ctx["now"], MAX_BOOT, STALL_SECONDS)


@pytest.fixture
def ctx():
    return {
        "now": NOW,
        "store": FakeStore(),
        "workers": FakeWorkers(),
        "fs": FakeFs(),
        "spin_port": FakeSpinPort(),
        "spin_cap": 3,
    }


@given(parsers.parse("the spin cap is {cap:d}"))
def _spin_cap(ctx, cap):
    ctx["spin_cap"] = cap


@given("a worker has claimed a step")
def _claimed(ctx):
    step = ctx["store"].create_step("build: t", step="build", role="agent")
    ctx["store"].update_state(step, "in_progress")
    ctx["store"].assign(step, "sp-1")
    ctx["step"] = step
    ctx["pid"] = 4242
    ctx["log"] = "/logs/%s.log" % step
    entry = {
        "spawnid": "sp-1", "pid": ctx["pid"], "step": step,
        "started": ctx["now"] - MAX_BOOT - 1, "log": ctx["log"],
    }
    ctx["worker_entry"] = entry
    ctx["workers"].register(entry, alive=True)


def _kill_worker(ctx):
    ctx["workers"].kill_worker(ctx["pid"])


@given("the worker died having done no work")
def _died_no_work(ctx):
    _kill_worker(ctx)
    ctx["fs"].files[ctx["log"]] = _NO_WORK_LOG


@given("the worker died having shown real session activity")
def _died_real_activity(ctx):
    _kill_worker(ctx)
    ctx["fs"].files[ctx["log"]] = _REAL_ACTIVITY_LOG


@given(parsers.parse(
    'the worker died having done no work, its log ending with "{last_line}"'
))
def _died_no_work_with_line(ctx, last_line):
    _kill_worker(ctx)
    ctx["fs"].files[ctx["log"]] = ("session started\n%s" % last_line).encode()
    ctx["expected_last_line"] = last_line


@given(parsers.parse("the step has previously died this way {prior_count:d} times in a row"))
def _prior_streak(ctx, prior_count):
    if prior_count == 0:
        return
    state = ctx["spin_port"].load()
    steps = dict(state.get("steps") or {})
    steps[ctx["step"]] = {"count": prior_count, "since": ctx["now"] - 10, "last_line": "prior"}
    state["steps"] = steps
    ctx["spin_port"].save(state)


@given(parsers.parse(
    "the step has previously died having done no work {prior_count:d} times in a row"
))
def _prior_streak_no_work(ctx, prior_count):
    since = ctx["now"] - 42
    state = ctx["spin_port"].load()
    steps = dict(state.get("steps") or {})
    steps[ctx["step"]] = {"count": prior_count, "since": since, "last_line": "prior"}
    state["steps"] = steps
    ctx["spin_port"].save(state)
    ctx["expected_elapsed_marker"] = "~42s"


@given("no dead worker is on record for the step")
def _no_dead_worker(ctx):
    ctx["workers"]._workers = [
        w for w in ctx["workers"]._workers if w.get("step") != ctx["step"]
    ]


@given("the worker's log last grew more than the stall threshold ago")
def _log_stale(ctx):
    ctx["workers"]._log_mtimes = getattr(ctx["workers"], "_log_mtimes", {})
    ctx["workers"]._log_mtimes[ctx["log"]] = ctx["now"] - STALL_SECONDS - 1


@given("the worker's log contains no terminal marker")
def _no_terminal_marker(ctx):
    non_terminal = json.dumps(
        {
            "type": "assistant",
            "message": {"content": [{"type": "tool_use", "input": {"command": "echo hi"}}]},
        }
    )
    ctx["fs"].files[ctx["log"]] = non_terminal.encode()


@given("the worker is past its boot window")
def _past_boot(ctx):
    ctx["worker_entry"]["started"] = ctx["now"] - MAX_BOOT - 1


@given("a step was parked after its worker died 3 times in a row with no work")
def _step_parked(ctx):
    step = ctx["store"].create_step("build: t", step="build", role="agent")
    ctx["step"] = step
    state = ctx["spin_port"].load()
    steps = dict(state.get("steps") or {})
    steps[step] = {"count": 3, "since": ctx["now"] - 100, "last_line": "prior"}
    state["steps"] = steps
    ctx["spin_port"].save(state)
    ParkStepUseCase(ctx["store"]).execute(
        ParkInput(
            step=step, observation="died 3 times in a row with no work", decision="check auth"
        )
    )


@when("the pool sweeps")
def _sweep(ctx):
    _run_sweep(ctx)


@when("I unblock the step")
def _unblock(ctx):
    flow = FlowService(
        FlowFakeFs(metas={"agent": {"model": "sonnet", "step": "build"}}), ctx["store"]
    )
    UnblockStepUseCase(ctx["store"], flow, spin_port=ctx["spin_port"]).execute(
        UnblockInput(step=ctx["step"])
    )


@when("the step's worker later dies again having done no work")
def _dies_again(ctx):
    spawnid = "sp-again"
    pid = 4343
    log = "/logs/%s-again.log" % ctx["step"]
    ctx["store"].update_state(ctx["step"], "in_progress")
    ctx["store"].assign(ctx["step"], spawnid)
    ctx["fs"].files[log] = _NO_WORK_LOG
    ctx["workers"]._workers.append(
        {"spawnid": spawnid, "pid": pid, "step": ctx["step"], "started": ctx["now"] - 200, "log": log}
    )
    _run_sweep(ctx)


@given(parsers.parse("a worker's log has {log_contents}"))
def _log_has(ctx, log_contents):
    ctx["log_lines"] = _LOG_CONTENT_BY_DESCRIPTION[log_contents].splitlines()


@then(parsers.parse("the log is judged to show session activity: {activity_found}"))
def _activity_found(ctx, activity_found):
    expected = activity_found == "yes"
    assert saw_session_activity(ctx["log_lines"]) is expected


@then(parsers.re(r"^the step is (?P<verdict>reclaimed to ready|parked for a human)$"))
def _verdict(ctx, verdict):
    node = ctx["store"].get_node(ctx["step"])
    if verdict == "reclaimed to ready":
        assert node.state == "ready"
        assert node.role == "agent"
        assert ctx["step"] in ctx["result"].swept
        assert ctx["step"] not in ctx["result"].parked
    elif verdict == "parked for a human":
        assert node.role == "human"
        assert ctx["step"] in ctx["result"].parked
        assert ctx["step"] not in ctx["result"].swept
    else:
        raise ValueError(verdict)


@then("the step's no-work streak is reset to zero")
def _streak_reset(ctx):
    steps = ctx["spin_port"].load().get("steps") or {}
    assert ctx["step"] not in steps


@then("the step's no-work streak is unaffected")
def _streak_unaffected(ctx):
    steps = ctx["spin_port"].load().get("steps") or {}
    assert ctx["step"] not in steps


@then("the worker is killed")
def _killed(ctx):
    assert ctx["pid"] in ctx["workers"].killed


@then("the step is parked for a human, not reclaimed")
def _parked_not_reclaimed(ctx):
    assert ctx["step"] in ctx["result"].parked
    assert ctx["step"] not in ctx["result"].swept


@then("the step's role is human")
def _role_is_human(ctx):
    assert ctx["store"].get_node(ctx["step"]).role == "human"


@then("the park's observation states the step died 3 times in a row with no observed work")
def _observation_count(ctx):
    reason = ctx["store"].get_node(ctx["step"]).park.reason or ""
    assert "3 times in a row" in reason
    assert "no observed" in reason.lower()


@then("the park's observation states the elapsed span since the first death in the streak")
def _observation_elapsed(ctx):
    reason = ctx["store"].get_node(ctx["step"]).park.reason or ""
    assert ctx["expected_elapsed_marker"] in reason


@then("the park's observation states the last line of the most recent worker's log")
def _observation_last_line(ctx):
    reason = ctx["store"].get_node(ctx["step"]).park.reason or ""
    assert ctx["expected_last_line"] in reason


@then("the step's notes carry a BLOCKED note")
def _blocked_note(ctx):
    notes = ctx["store"].get_node(ctx["step"]).notes or ""
    assert "BLOCKED:" in notes


@then("the step is reclaimed to ready, not parked")
def _reclaimed_not_parked(ctx):
    assert ctx["step"] in ctx["result"].swept
    assert ctx["step"] not in ctx["result"].parked
    assert ctx["store"].get_node(ctx["step"]).state == "ready"
