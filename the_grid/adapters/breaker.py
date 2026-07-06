import json
import os

from the_grid.ports.breaker import BreakerPort


def breaker_path(root):
    return os.path.join(root, "logs", "breaker.json")


def load(root):
    p = breaker_path(root)
    if not os.path.exists(p):
        return {}
    try:
        return json.loads(open(p).read())
    except Exception:
        return {}


def save(root, state):
    os.makedirs(os.path.join(root, "logs"), exist_ok=True)
    with open(breaker_path(root), "w") as f:
        f.write(json.dumps(state, indent=2))


class BreakerAdapter(BreakerPort):
    def __init__(self, config):
        self._config = config

    def load(self):
        return load(self._config.grid_root())

    def save(self, state):
        return save(self._config.grid_root(), state)
