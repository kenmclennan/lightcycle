import json
import os
import sys

from lightcycle.ports.memory_gate_status import MemoryGateStatusPort


def memory_gate_status_path(root):
    return os.path.join(root, "logs", "memory_gate.json")


def load(root):
    p = memory_gate_status_path(root)
    if not os.path.exists(p):
        return {}
    try:
        with open(p) as f:
            return json.loads(f.read())
    except Exception as e:
        sys.stderr.write("warning: could not read memory gate state %s: %s\n" % (p, e))
        return {}


def save(root, state):
    os.makedirs(os.path.join(root, "logs"), exist_ok=True)
    p = memory_gate_status_path(root)
    tmp = "%s.%d.tmp" % (p, os.getpid())
    with open(tmp, "w") as f:
        f.write(json.dumps(state, indent=2))
    os.replace(tmp, p)


class MemoryGateStatusAdapter(MemoryGateStatusPort):
    def __init__(self, config):
        self._config = config

    def load(self):
        return load(self._config.data_root())

    def save(self, state):
        return save(self._config.data_root(), state)
