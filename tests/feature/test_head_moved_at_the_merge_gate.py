import time
import pytest
from pytest_bdd import given, scenarios, then, when

from lightcycle.application.flow import CompleteStepUseCase
from lightcycle.application.pool.pr_writes import InlinePrWrites
from lightcycle.application.pool import MonitorPrsUseCase
from tests.support.fake_view_freshness import AlwaysConfirmed
from tests.support.fake_fs import flow_from_metas
from tests.support.fake_github import FakeGitHub
from tests.support.fake_store import FakeStore
from tests.unit.test_dispatch_pr_feedback import _FlowAdapter, plant_pr
from tests.unit.test_monitor_prs import FakeWorktrees

scenarios("head-moved-at-the-merge-gate.feature")

_URL = "https://github.com/x/y/pull/7"
_BASE = "acme/widget@main"


def _flow(with_hook):
    gate = {
        "model": "sonnet",
        "step": "watch-step",
        "routes": {"merged": "done-step", "head-moved": "ci-step"},
        "on_pr_merge": "merged",
    }
    if with_hook:
        gate["on_pr_head_moved"] = "head-moved"
    return flow_from_metas({"watcher": gate}, disposition={"merged": "completed"})


class _World:
    def __init__(self):
        self.store = FakeStore()
        self.heads = {_URL: "aaa"}
        self.behind = set()
        self.merged = set()
        self.strict = set()
        self.github = None
        self.monitor = None
        self.item = None
        self.gate = None
        self.runs = []

    def start(self, with_hook):
        self.github = FakeGitHub(
            merged_prs=self.merged, behind_prs=self.behind, head_shas=self.heads,
            strict_bases=self.strict,
        )
        self.heads = self.github._head_shas
        self.behind = self.github._behind
        self.merged = self.github._merged
        self.strict = self.github._strict_bases
        flow = _FlowAdapter(_flow(with_hook))
        self.item = self.store.create_item("feature", "d")
        plant_pr(self.store, self.item, _URL)
        self.gate = self.store.create_step(stage="watch-step", role="agent", item=self.item)
        self.monitor = MonitorPrsUseCase(
            self.store, self.github, FakeWorktrees(), flow, CompleteStepUseCase(self.store, flow),
            trusted_authors=lambda: frozenset(), held_shortcode=lambda: "HLD",
            writes=InlinePrWrites(self.github, time.monotonic), ci_clock=time.monotonic, ci_poll_seconds=lambda: 60, ci_ceiling_seconds=lambda: 3600, ci_start_window_seconds=lambda: 600, ci_no_workflows_wait_seconds=lambda: 60, ci_unconfirmed_note_polls=lambda: 3, ci_wall_clock=lambda: 10000.0, ci_views=AlwaysConfirmed(),
        )


@pytest.fixture
def world():
    return _World()


@given("an item waits at a gate declaring pr_head_moved with outcome head-moved")
def _hooked(world):
    world.start(True)


@given("an item waits at a gate that does not declare pr_head_moved")
def _plain(world):
    world.start(False)


@given("the gate has seen the PR head")
def _seen(world):
    world.runs.append(world.monitor.execute())


@given("the PR is behind a base that requires an up-to-date branch")
def _behind(world):
    world.behind.add(_URL)
    world.strict.add(_BASE)


@when("the PR head changes")
def _push(world):
    world.heads[_URL] = "bbb"


@when("the PR is merged")
def _merge(world):
    world.merged.add(_URL)


@when("the monitor runs")
def _run(world):
    world.runs.append(world.monitor.execute())


@then("the gate step is done")
def _done(world):
    assert world.store.get_node(world.gate).state == "done"


@then("the gate step is not done")
def _not_done(world):
    assert world.store.get_node(world.gate).state != "done"


@then("the gate step carries the update-branch note")
def _note(world):
    assert "CI is re-running" in (world.store.get_node(world.gate).notes or "")


@then("the monitor reports the item as head-moved")
def _reports_moved(world):
    assert any(world.item in r.head_moved for r in world.runs)


@then("the monitor reports the item as merged")
def _reports_merged(world):
    assert any(world.item in r.merged for r in world.runs)


@then("the monitor does not report the item as head-moved")
def _not_moved(world):
    assert all(world.item not in r.head_moved for r in world.runs)
