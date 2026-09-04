import json
import os
import sys

from lightcycle.ports.spin import SpinPort


def spin_path(root):
    return os.path.join(root, "logs", "spin.json")


def load(root):
    p = spin_path(root)
    if not os.path.exists(p):
        return {}
    try:
        return json.loads(open(p).read())
    except Exception as e:
        sys.stderr.write("warning: could not read spin state %s: %s\n" % (p, e))
        return {}


def save(root, state):
    os.makedirs(os.path.join(root, "logs"), exist_ok=True)
    with open(spin_path(root), "w") as f:
        f.write(json.dumps(state, indent=2))


class SpinAdapter(SpinPort):
    def __init__(self, config):
        self._config = config

    def load(self):
        return load(self._config.data_root())

    def save(self, state):
        return save(self._config.data_root(), state)
