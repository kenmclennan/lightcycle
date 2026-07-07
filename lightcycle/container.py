from lightcycle.adapters.breaker import BreakerAdapter
from lightcycle.adapters.fsio import FsAdapter
from lightcycle.adapters.github import GitHubEventsAdapter
from lightcycle.adapters.gitio import GitAdapter
from lightcycle.adapters.lock import RunLockAdapter
from lightcycle.adapters.spawner import SpawnerAdapter
from lightcycle.adapters.sqlite_store import SqliteStore
from lightcycle.adapters.workers import WorkersAdapter
from lightcycle.config import Config


class Container:
    def __init__(
        self, *, config=None, store=None, git=None, spawner=None, workers=None, fs=None,
        github=None, lock=None, breaker=None, now=None,
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
