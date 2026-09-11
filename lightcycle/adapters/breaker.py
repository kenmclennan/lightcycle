import json
import os
import sys

from lightcycle.ports.breaker import BreakerPort


def breaker_path(root):
    return os.path.join(root, "logs", "breaker.json")


def load(root):
    p = breaker_path(root)
    if not os.path.exists(p):
        return {}
    try:
        with open(p) as f:
            return json.loads(f.read())
    except Exception as e:
        sys.stderr.write("warning: could not read breaker state %s: %s\n" % (p, e))
        return {"open": True, "reset_at": 0}


def save(root, state):
    os.makedirs(os.path.join(root, "logs"), exist_ok=True)
    p = breaker_path(root)
    tmp = "%s.%d.tmp" % (p, os.getpid())
    with open(tmp, "w") as f:
        f.write(json.dumps(state, indent=2))
    os.replace(tmp, p)


class BreakerAdapter(BreakerPort):
    def __init__(self, config):
        self._config = config

    def load(self):
        return load(self._config.data_root())

    def save(self, state):
        return save(self._config.data_root(), state)
