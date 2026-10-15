import json
import os
import sys

from lightcycle.ports.config_reload_status import ConfigReloadStatusPort


def config_reload_status_path(root):
    return os.path.join(root, "logs", "config_reload.json")


def load(root):
    p = config_reload_status_path(root)
    if not os.path.exists(p):
        return {}
    try:
        with open(p) as f:
            return json.loads(f.read())
    except Exception as e:
        sys.stderr.write("warning: could not read config reload state %s: %s\n" % (p, e))
        return {}


def save(root, state):
    os.makedirs(os.path.join(root, "logs"), exist_ok=True)
    p = config_reload_status_path(root)
    tmp = "%s.%d.tmp" % (p, os.getpid())
    with open(tmp, "w") as f:
        f.write(json.dumps(state, indent=2))
    os.replace(tmp, p)


class ConfigReloadStatusAdapter(ConfigReloadStatusPort):
    def __init__(self, config):
        self._config = config

    def load(self):
        return load(self._config.data_root())

    def save(self, state):
        return save(self._config.data_root(), state)
