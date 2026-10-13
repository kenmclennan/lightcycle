import os

from lightcycle.ports.drain import PoolDrainPort


def drain_path(root):
    return os.path.join(root, ".lc-drain")


class PoolDrainAdapter(PoolDrainPort):
    def __init__(self, config):
        self._config = config

    def request(self):
        with open(drain_path(self._config.data_root()), "a"):
            pass

    def requested(self):
        return os.path.exists(drain_path(self._config.data_root()))

    def clear(self):
        try:
            os.remove(drain_path(self._config.data_root()))
        except FileNotFoundError:
            pass
