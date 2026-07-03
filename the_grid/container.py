from the_grid.adapters.fsio import FsAdapter
from the_grid.adapters.github import GitHubEventsAdapter
from the_grid.adapters.gitio import GitAdapter
from the_grid.adapters.lock import RunLockAdapter
from the_grid.adapters.spawner import SpawnerAdapter
from the_grid.adapters.store import BdStore
from the_grid.adapters.workers import WorkersAdapter
from the_grid.config import Config


class Container:
    def __init__(
        self, *, config=None, store=None, git=None, spawner=None, workers=None, fs=None,
        github=None, lock=None,
    ):
        self.config = config if config is not None else Config()
        self.store = store if store is not None else BdStore(self.config)
        self.git = git if git is not None else GitAdapter()
        self.spawner = spawner if spawner is not None else SpawnerAdapter(self.config)
        self.workers = workers if workers is not None else WorkersAdapter(self.config)
        self.fs = fs if fs is not None else FsAdapter(self.config)
        self.github = github if github is not None else GitHubEventsAdapter()
        self.lock = lock if lock is not None else RunLockAdapter(self.config)
