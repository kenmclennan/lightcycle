import os
import tempfile

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from lightcycle.adapters.lock import RunLockAdapter
from lightcycle.application.pool import AcquireRunLockUseCase, PoolRunningUseCase

scenarios("pool-running-state.feature")


class FakeConfig:
    def __init__(self, root):
        self._root = root

    def engine_root(self):
        return self._root

    def data_root(self):
        return self._root

    def prompts_root(self):
        return self._root


@pytest.fixture
def ctx():
    root = tempfile.mkdtemp()
    return {"root": root, "lock": RunLockAdapter(FakeConfig(root))}


def _lock_path(ctx):
    return os.path.join(ctx["root"], ".lc-run.pid")


def _snapshot(ctx):
    path = _lock_path(ctx)
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return f.read()


@given("the run lock file records the pid of a live process")
def _live_pid(ctx):
    with open(_lock_path(ctx), "w") as f:
        f.write(str(os.getpid()))
    ctx["before"] = _snapshot(ctx)


@given("no run lock file exists")
def _no_lock_file(ctx):
    ctx["before"] = _snapshot(ctx)


@given("the run lock file records the pid of a process that is not alive")
def _dead_pid(ctx):
    with open(_lock_path(ctx), "w") as f:
        f.write("999999")
    ctx["before"] = _snapshot(ctx)


@when("the pool-running state is read")
def _read_once(ctx):
    ctx["result"] = PoolRunningUseCase(ctx["lock"]).execute()


@when(parsers.parse("the pool-running state is read {count:d} times"))
def _read_many(ctx, count):
    for _ in range(count):
        PoolRunningUseCase(ctx["lock"]).execute()


@when("a real run lock acquisition is then attempted")
def _acquire(ctx):
    ctx["acquire_result"] = AcquireRunLockUseCase(ctx["lock"]).execute()


@then(parsers.parse("it reports the pool as {expected}"))
def _reports(ctx, expected):
    assert ctx["result"].running == (expected == "running")


@then("the run lock file is untouched")
def _untouched(ctx):
    assert _snapshot(ctx) == ctx["before"]


@then("the acquisition succeeds")
def _acquisition_succeeds(ctx):
    assert ctx["acquire_result"].acquired
