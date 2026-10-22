import json
import os
import sys

from lightcycle.domain.pool import tick_timing_from_state
from lightcycle.ports.tick_timing_status import TickTimingStatusPort


def tick_timing_status_path(root):
    return os.path.join(root, "tick-timing.json")


def load(root):
    p = tick_timing_status_path(root)
    if not os.path.exists(p):
        return None
    try:
        with open(p) as f:
            return tick_timing_from_state(json.loads(f.read()))
    except Exception as e:
        sys.stderr.write("warning: could not read tick timing %s: %s\n" % (p, e))
        return None


def save(root, timing):
    p = tick_timing_status_path(root)
    tmp = "%s.%d.tmp" % (p, os.getpid())
    try:
        os.makedirs(root, exist_ok=True)
        with open(tmp, "w") as f:
            f.write(json.dumps(timing.as_dict(), indent=2))
        os.replace(tmp, p)
    except OSError as e:
        sys.stderr.write("warning: could not write tick timing %s: %s\n" % (p, e))


class TickTimingStatusAdapter(TickTimingStatusPort):
    def __init__(self, config):
        self._config = config

    def load(self):
        return load(self._config.data_root())

    def save(self, timing):
        return save(self._config.data_root(), timing)
