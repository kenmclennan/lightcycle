import json
import os
import sys

from lightcycle.domain.pool import GuidanceSyncState
from lightcycle.ports.guidance_sync_status import GuidanceSyncStatusPort


def guidance_sync_status_path(root):
    return os.path.join(root, "logs", "guidance_sync.json")


def load(root):
    p = guidance_sync_status_path(root)
    if not os.path.exists(p):
        return None
    try:
        with open(p) as f:
            return GuidanceSyncState.from_dict(json.loads(f.read()))
    except Exception as e:
        sys.stderr.write("warning: could not read guidance sync state %s: %s\n" % (p, e))
        return None


def save(root, state):
    os.makedirs(os.path.join(root, "logs"), exist_ok=True)
    p = guidance_sync_status_path(root)
    tmp = "%s.%d.tmp" % (p, os.getpid())
    with open(tmp, "w") as f:
        f.write(json.dumps(state.as_dict(), indent=2))
    os.replace(tmp, p)


class GuidanceSyncStatusAdapter(GuidanceSyncStatusPort):
    def __init__(self, config):
        self._config = config

    def load(self):
        return load(self._config.data_root())

    def save(self, state):
        return save(self._config.data_root(), state)
