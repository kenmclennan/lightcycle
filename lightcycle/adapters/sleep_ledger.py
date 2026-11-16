import json
import os
import sys

from lightcycle.ports.sleep_ledger import SleepLedgerPort


def sleep_ledger_path(root):
    return os.path.join(root, "sleep-ledger.json")


def load(root):
    p = sleep_ledger_path(root)
    if not os.path.exists(p):
        return {}
    try:
        with open(p) as f:
            state = json.loads(f.read())
        if not isinstance(state, dict):
            raise ValueError("not an object")
        return state
    except Exception as e:
        sys.stderr.write("warning: could not read sleep ledger %s: %s\n" % (p, e))
        return {}


def save(root, state):
    p = sleep_ledger_path(root)
    tmp = "%s.%d.tmp" % (p, os.getpid())
    try:
        os.makedirs(root, exist_ok=True)
        with open(tmp, "w") as f:
            f.write(json.dumps(state, indent=2))
        os.replace(tmp, p)
    except OSError as e:
        sys.stderr.write("warning: could not write sleep ledger %s: %s\n" % (p, e))


class SleepLedgerAdapter(SleepLedgerPort):
    def __init__(self, config):
        self._config = config

    def load(self):
        return load(self._config.data_root())

    def save(self, state):
        return save(self._config.data_root(), state)
