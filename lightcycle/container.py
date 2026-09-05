from lightcycle.adapters.backup import SqliteBackupAdapter
from lightcycle.adapters.breaker import BreakerAdapter
from lightcycle.adapters.fsio import FsAdapter
from lightcycle.adapters.github import GitHubEventsAdapter
from lightcycle.adapters.gitio import GitAdapter
from lightcycle.adapters.launcher import LauncherAdapter
from lightcycle.adapters.lock import RunLockAdapter
from lightcycle.adapters.spawner import SpawnerAdapter
from lightcycle.adapters.spin import SpinAdapter
from lightcycle.adapters.sqlite_store import SqliteStore
from lightcycle.adapters.workers import WorkersAdapter
from lightcycle.adapters.workflow_source import WorkflowSourceAdapter
from lightcycle.config import Config


class Container:
    def __init__(
        self, *, config=None, store=None, git=None, spawner=None, workers=None, fs=None,
        github=None, lock=None, breaker=None, backup=None, workflow_source=None, launcher=None,
        spin=None, now=None,
    ):
        self.config = config if config is not None else Config()
        self.store = store if store is not None else SqliteStore(self.config, now=now)
        self.git = git if git is not None else GitAdapter()
        self.spawner = spawner if spawner is not None else SpawnerAdapter(self.config)
        self.workers = workers if workers is not None else WorkersAdapter(self.config)
        self.fs = fs if fs is not None else FsAdapter(self.config)
        self.github = github if github is not None else GitHubEventsAdapter()
        self.lock = lock if lock is not None else RunLockAdapter(self.config)
        self.breaker = breaker if breaker is not None else BreakerAdapter(self.config)
        self.spin = spin if spin is not None else SpinAdapter(self.config)
        self.backup = backup if backup is not None else SqliteBackupAdapter(self.config)
        self.workflow_source = (
            workflow_source if workflow_source is not None
            else WorkflowSourceAdapter(self.config)
        )
        self.launcher = launcher if launcher is not None else LauncherAdapter()

    def flow_service(self):
        return make_flow_service(self.fs, self.store, self.config, self.workflow_source)

    def worktrees(self):
        return worktrees_for(self)


def make_flow_service(fs, store, config, workflow_source):
    from lightcycle.application.services.flow import FlowService

    return FlowService(fs, store, config, workflow_source)


def make_worktrees(store, git, fs, config, flow):
    from lightcycle.application.services.worktree import WorktreeService

    return WorktreeService(store, git, fs, config, flow)


def worktrees_for(container, flow=None):
    if flow is None:
        flow = make_flow_service(
            container.fs, container.store, container.config, container.workflow_source
        )
    return make_worktrees(
        container.store, container.git, container.fs, container.config, flow,
    )
