import json
import os

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

import lightcycle.cli as cli
from lightcycle.adapters.workers import register_worker, workers_state, write_workers
from lightcycle.domain.work.worker_log import worker_log_filename
from tests.support.harness import Harness

scenarios("durable-log-resolution.feature")


@pytest.fixture
def ctx():
    return {}


@pytest.fixture(autouse=True)
def _isolate():
    saved = dict(os.environ)
    orig = cli.container()
    yield
    os.environ.clear()
    os.environ.update(saved)
    cli.set_container(orig)


@given("a flow where the coder builds the item")
def _flow(ctx):
    ctx["h"] = Harness(["coder"])


@given(parsers.parse('the item "{spec}" is filed at step "{step}"'))
def _filed(ctx, spec, step):
    rc, theme, err = ctx["h"].run(
        "new", "theme", "objective for %s" % spec, "--workflow", "lightcycle/spec-driven"
    )
    assert rc == 0, err
    title = os.path.splitext(os.path.basename(spec))[0]
    rc, item, err = ctx["h"].run("new", "item", title, "--parent", theme.strip())
    assert rc == 0, err
    item = item.strip()
    ctx["h"].run("attach", item, "spec", spec)
    rc, _out, err = ctx["h"].run("set", item, "--state", "active", "--step", step)
    assert rc == 0, err
    ctx["item"] = item


def _log_path(h, role, spawnid):
    return os.path.join(h.root, "logs", worker_log_filename(role, spawnid))


@given(parsers.parse(
    'worker "{spawnid}" has claimed and completed the build step with outcome "{outcome}"'
))
def _claimed_and_completed(ctx, spawnid, outcome):
    h = ctx["h"]
    role = "coder"
    log_path = _log_path(h, role, spawnid)
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "w") as f:
        f.write("worker log\n")
    register_worker(h.root, {
        "spawnid": spawnid, "role": role, "pid": os.getpid(), "pid_started": None,
        "log": log_path, "step": None, "started": 0,
    })
    rc, out, err = h.run_as_worker(spawnid, "claim", role)
    assert rc == 0, err
    claimed = json.loads(out)
    ctx["step_id"] = claimed["id"]
    ctx["spawnid"] = spawnid
    ctx["role"] = role
    ctx["log_path"] = log_path
    rc, out, err = h.run_as_worker(spawnid, "done", claimed["id"], outcome)
    assert rc == 0, err


@given(parsers.parse('the worker registry no longer has an entry for worker "{spawnid}"'))
def _registry_pruned(ctx, spawnid):
    h = ctx["h"]
    remaining = [w for w in workers_state(h.root) if w.get("spawnid") != spawnid]
    write_workers(h.root, remaining)


@given(parsers.parse('worker "{spawnid}"\'s log file still exists on disk'))
def _log_still_exists(ctx, spawnid):
    path = ctx["log_path"]
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write("worker log\n")


@given(parsers.parse('worker "{spawnid}"\'s log file does not exist on disk'))
def _log_missing(ctx, spawnid):
    path = ctx["log_path"]
    if os.path.exists(path):
        os.remove(path)


@given("the build step has never been claimed by a worker")
def _never_claimed(ctx):
    h = ctx["h"]
    step = next(t for t in h.store.all_nodes() if t.step == "build")
    ctx["step_id"] = step.id


def _resolve_via(h, surface, step_id, item):
    if surface == "the trace read path":
        rc, out, err = h.run("trace", item, "--json")
        assert rc == 0, err
        trace = json.loads(out)
        matches = [s for s in trace["steps"] if s["id"] == step_id]
        return bool(matches and matches[-1]["log"])
    if surface == "the logs command":
        rc, _out, _err = h.run("logs", step_id)
        return rc == 0
    raise ValueError("unknown surface: %s" % surface)


@when(parsers.parse("the build step's log is resolved via {surface}"))
def _resolve(ctx, surface):
    ctx["found"] = _resolve_via(ctx["h"], surface, ctx["step_id"], ctx["item"])


@when(parsers.parse('the log for role "{role}" is resolved via the logs command'))
def _resolve_role(ctx, role):
    rc, _out, _err = ctx["h"].run("logs", role)
    ctx["found"] = rc == 0


@then(parsers.parse("the {subject} is found"))
def _is_found(ctx, subject):
    assert ctx["found"], "expected %s to be found" % subject


@then(parsers.parse("the {subject} is not found"))
def _is_not_found(ctx, subject):
    assert not ctx["found"], "expected %s to not be found" % subject
