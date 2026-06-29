"""Container: constructs and holds the adapter graph behind the ports.

The composition root. cli builds one Container and resolves every adapter
through it; tests construct a Container with a FakeStore (and real or fake
peers) to inject test doubles without touching the wired code.
"""
from the_grid.adapters.fsio import FsAdapter
from the_grid.adapters.gitio import GitAdapter
from the_grid.adapters.spawner import SpawnerAdapter
from the_grid.adapters.store import BdStore
from the_grid.adapters.workers import WorkersAdapter


class Container:

    def __init__(self, *, store=None, git=None, spawner=None, workers=None, fs=None):
        self.store = store if store is not None else BdStore()
        self.git = git if git is not None else GitAdapter()
        self.spawner = spawner if spawner is not None else SpawnerAdapter()
        self.workers = workers if workers is not None else WorkersAdapter()
        self.fs = fs if fs is not None else FsAdapter()
