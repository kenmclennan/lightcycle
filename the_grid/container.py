"""Container: constructs and holds the adapter graph behind the ports.

The composition root. Config is built first (the environment boundary) and
threaded into every adapter that needs a root, the child env, or a tunable.
cli resolves config and adapters through the one Container; tests construct a
Container with a FakeStore (and real or fake peers) to inject test doubles.
"""
from the_grid.adapters.fsio import FsAdapter
from the_grid.adapters.github import GitHubEventsAdapter
from the_grid.adapters.gitio import GitAdapter
from the_grid.adapters.spawner import SpawnerAdapter
from the_grid.adapters.store import BdStore
from the_grid.adapters.workers import WorkersAdapter
from the_grid.config import Config


class Container:

    def __init__(self, *, config=None, store=None, git=None, spawner=None, workers=None, fs=None,
                 github=None):
        self.config = config if config is not None else Config()
        self.store = store if store is not None else BdStore(self.config)
        self.git = git if git is not None else GitAdapter()
        self.spawner = spawner if spawner is not None else SpawnerAdapter(self.config)
        self.workers = workers if workers is not None else WorkersAdapter(self.config)
        self.fs = fs if fs is not None else FsAdapter(self.config)
        self.github = github if github is not None else GitHubEventsAdapter()
