import json
import os

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

import lightcycle.cli as cli
from lightcycle.ports.github import Comment
from tests.support.fake_github import FakeGitHub
from tests.support.harness import Harness

scenarios("feedback-cycle.feature")

_PUSH_TIME = 1000.0
_MENTION_TIME = 1500.0

_WORKFLOW_TEXT = (
    "entry: await-merge\n\n"
    "hooks:\n"
    "  pr_feedback    await-merge  handle-feedback\n"
    "  mention_token  await-merge  @lc\n"
)


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


@given(parsers.parse(
    'a flow where "{watched_step}" reacts to "{token}" PR feedback with "{feedback_step}"'
))
def _flow(ctx, watched_step, token, feedback_step):
    ctx["watched_step_name"] = watched_step
    ctx["gh"] = FakeGitHub(push_time=_PUSH_TIME)
    ctx["h"] = Harness(
        [feedback_step],
        github=ctx["gh"],
        extra_steps={watched_step: "# %s\n" % watched_step},
        workflow_text=_WORKFLOW_TEXT,
    )


@given(parsers.parse('the item "{spec}" is awaiting merge with PR "{pr_url}"'))
def _awaiting_merge(ctx, spec, pr_url):
    rc, theme, err = ctx["h"].run(
        "new", "theme", "objective for %s" % spec, "--workflow", "lightcycle/spec-driven"
    )
    assert rc == 0, err
    title = os.path.splitext(os.path.basename(spec))[0]
    rc, item, err = ctx["h"].run("new", "item", title, "--parent", theme.strip())
    assert rc == 0, err
    item = item.strip()
    ctx["h"].run("attach", item, "spec", spec)
    rc, step, err = ctx["h"].run(
        "set", item, "--state", "active", "--step", ctx["watched_step_name"]
    )
    assert rc == 0, err
    ctx["h"].run("attach", item, "pr", pr_url)
    ctx["item"] = item
    ctx["watched_step"] = step.strip()


@given(parsers.parse('the PR has an outstanding "{token}" mention'))
def _outstanding_mention(ctx, token):
    ctx["gh"]._timed_comments.append((
        _MENTION_TIME,
        Comment(
            author="reviewer", body="%s please fix this" % token, is_top_level=True,
            id="mention-1", created_at=_MENTION_TIME,
        ),
    ))


@when("the pool ticks")
@when("the pool ticks again")
def _tick(ctx):
    rc, out, err = ctx["h"].run("start", "--once")
    assert rc == 0, err


@when("the handle-feedback step is marked done without clearing the feedback")
def _closed_without_clearing(ctx):
    rc, out, err = ctx["h"].run("claim", "handle-feedback")
    assert rc == 0, err
    step_id = json.loads(out)["id"]
    rc, out, err = ctx["h"].run("done", step_id, "done")
    assert rc == 0, err


@when("the handle-feedback step replies and advances the watermark")
def _replied_and_advanced(ctx):
    rc, out, err = ctx["h"].run("claim", "handle-feedback")
    assert rc == 0, err
    step_id = json.loads(out)["id"]
    rc, out, err = ctx["h"].run("done", step_id, "done")
    assert rc == 0, err
    rc, out, err = ctx["h"].run(
        "attach", ctx["watched_step"], "feedback-watermark", str(_MENTION_TIME), "--replace"
    )
    assert rc == 0, err


@then(parsers.parse('there is one ready step for "{role}"'))
def _one_ready(ctx, role):
    assert len(ctx["h"].ready_steps(role)) == 1


@then(parsers.parse('there are no ready steps for "{role}"'))
def _no_ready(ctx, role):
    assert ctx["h"].ready_steps(role) == []


@then("there is still exactly one handle-feedback step in total")
def _one_total(ctx):
    assert len(ctx["h"].store.steps_at_step("handle-feedback")) == 1
