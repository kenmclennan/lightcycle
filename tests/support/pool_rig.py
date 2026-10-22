import importlib
import inspect
import os
import tempfile
from pathlib import Path

from lightcycle.application.pool.tick import TickInput
from lightcycle.config import _SEED_KEYS, Config
from lightcycle.container import Container
from lightcycle.ports.spawner import SpawnerPort
from tests.support.fake_drain import FakeDrain
from tests.support.fake_fs import FakeFs
from tests.support.fake_git import FakeGit
from tests.support.fake_github import FakeGitHub
from tests.support.fake_github_budget_status import FakeGithubBudgetStatus
from tests.support.fake_tick_timing_status import FakeTickTimingStatus
from tests.support.fake_github_poll_runner import (
    BlockingGithubPollRunner,
    InlineGithubPollRunner,
)
from tests.support.fake_machine import FakeMachine
from tests.support.fake_script_runner import FakeScriptRunner
from tests.support.fake_spin import FakeSpinPort
from tests.support.fake_store import FakeStore
from tests.support.fake_workers import FakeWorkers
from tests.support.pool_crash import crash_on
from tests.support.sim_clock import SimClock

_PROJECT = "acme/app"
_REPO = "app"


class _RigSpawner(SpawnerPort):
    def __init__(self):
        self.spawned = []

    def spawn_worker(self, role):
        self.spawned.append(role)

    def spawn_pool(self):
        return None


class RigFlow:
    def __init__(self, flow, phase=None):
        self._flow = flow
        self._phase = phase

    def clear_cache(self):
        return None

    def workflow_for(self, step):
        return "wf"

    def unpinned_workflow(self, node):
        return None

    def load_flow(self, name=None, project=None):
        return self._flow

    def flow_for(self, node):
        return self._flow

    def flow_next(self, step, outcome, name=None, project=None):
        return self._flow.next(step, outcome)

    def outcomes_for(self, step, name=None, project=None):
        return sorted(self._flow.step_def(step).routes.keys())

    def meta_for_step(self, step, name=None, project=None):
        return {}

    def owner_of(self, step, name=None, project=None):
        return self._flow.step_def(step).owner

    def escalated_transition(self, transition, outcome, history, name=None, project=None):
        return self._flow.escalated_transition(transition, outcome, history, lambda key: None)

    def phase_for(self, node):
        if self._phase is not None:
            return self._phase
        return self._flow.step_def(getattr(node, "stage", None)).phase

    def phase_for_stage(self, stage, name=None):
        if self._phase is not None:
            return self._phase
        return self._flow.step_def(stage).phase

    def ends_pass(self, stage, outcome, name=None):
        return False

    def workspace_for_node(self, node):
        return "project"

    def workspace_for_phase(self, node, phase):
        return "project"


def _write_config(home, overrides):
    values = dict(_SEED_KEYS)
    values["projects"] = home
    values["specs"] = home
    values["max-agents"] = "0"
    values["backups-dir"] = tempfile.mkdtemp()
    values["backup-interval-minutes"] = "100000"
    for key, value in overrides.items():
        values[key.replace("_", "-")] = str(value)
    path = os.path.join(tempfile.mkdtemp(), "config")
    Path(path).write_text("".join("%s: %s\n" % (k, v) for k, v in values.items()))
    return Config(environ={"LC_HOME": home, "LC_CONFIG": path})


def _default_run_groups():
    try:
        module = importlib.import_module("tests.support.fake_run_groups")
    except ImportError:
        return None
    return module.FakeRunGroups()


class PoolRig:
    def __init__(self, flow, *, clock=None, github=None, stepped_poll=False, config=None,
                 **fakes):
        self.clock = clock if clock is not None else SimClock()
        self.home = tempfile.mkdtemp()
        Path(self.home, "store.db").touch()
        self.target = os.path.join(self.home, "app")
        os.makedirs(self.target, exist_ok=True)
        self.flow = flow
        self.store = fakes.pop("store", None) or FakeStore(now=self.clock.iso)
        self.git = fakes.pop("git", None) or FakeGit(repos={self.target}, base="origin/main")
        self.fs = fakes.pop("fs", None) or FakeFs()
        self.workers = fakes.pop("workers", None) or FakeWorkers()
        self.spawner = fakes.pop("spawner", None) or _RigSpawner()
        self.github = github if github is not None else FakeGitHub()
        self.poll_runner = (
            BlockingGithubPollRunner() if stepped_poll else InlineGithubPollRunner())
        self.script_runner = fakes.pop("script_runner", None) or FakeScriptRunner(self.clock)
        self.run_groups = fakes.pop("run_groups", None) or _default_run_groups()
        self._extras = {
            "machine": fakes.pop("machine", None) or FakeMachine(),
            "drain": fakes.pop("drain", None) or FakeDrain(),
            "spin": fakes.pop("spin", None) or FakeSpinPort(),
            "github_budget_status": (
                fakes.pop("github_budget_status", None) or FakeGithubBudgetStatus()),
            "tick_timing_status": (
                fakes.pop("tick_timing_status", None) or FakeTickTimingStatus()),
        }
        self._extras.update(fakes)
        self.config = _write_config(self.home, config or {})
        if hasattr(self.store, "bind_config"):
            self.store.bind_config(self.config)
        self.store.add_project(_PROJECT, shortcode="APP", local_path=self.target)
        self.restarts = 0
        self.last = None
        self._since = None
        self._build()

    def _container(self):
        params = inspect.signature(Container.__init__).parameters
        wanted = dict(
            config=self.config, store=self.store, git=self.git, spawner=self.spawner,
            workers=self.workers, fs=self.fs, github=self.github,
            github_poll_runner=self.poll_runner, script_runner=self.script_runner,
            run_groups=self.run_groups, clock=self.clock, monotonic=self.clock,
            **self._extras)
        return Container(**{k: v for k, v in wanted.items() if k in params and v is not None})

    def _build(self):
        self.container = self._container()
        self.flow_service = RigFlow(self.flow) if not isinstance(
            self.flow, RigFlow) else self.flow
        self.tick_use_case = self.container.tick(flow=self.flow_service)
        self.worktrees = self.container.worktrees(flow=self.flow_service)
        self.poll_gate = self.tick_use_case._github_poll_gate
        self.snapshot = self.poll_gate._snapshot

    def new_item(self, title):
        item = self.store.create_item(title, "a description")
        self.store.add_artifact(item, "repo", _REPO)
        return item

    def seed_worktree(self, run_id):
        run = self.store.get_run(run_id)
        self.git._registered.add(self.worktrees.path_for_run(run))
        self.git._branches.add((self.target, run.branch))

    def tick(self):
        self.last = self.tick_use_case.execute(TickInput(now=self.clock(), since=self._since))
        self._since = self.clock()
        return self.last

    def run(self, seconds, every=5, until=None):
        deadline = self.clock() + seconds
        while True:
            self.tick()
            if until is not None and until():
                return True
            if self.clock() >= deadline:
                return False
            self.clock.advance(every)

    def release_poll(self):
        self.poll_runner.release()

    def poll_between_ticks(self, after=0.0, reads=()):
        self.clock.advance(after)
        for pr in reads:
            self.snapshot.head_sha(pr)
        self.poll_gate.execute(self.clock())
        self.release_poll()

    def crash_after_gate(self, gate, nth=1):
        return crash_on(getattr(self.tick_use_case, "_" + gate), "execute", nth=nth, when="after")

    def crash_before_gate(self, gate, nth=1):
        return crash_on(getattr(self.tick_use_case, "_" + gate), "execute", nth=nth, when="before")

    def restart(self):
        orphan = getattr(self.script_runner, "orphan_running", None)
        if orphan is not None:
            orphan()
        self.restarts += 1
        self._since = None
        self._build()
