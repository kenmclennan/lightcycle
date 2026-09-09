import fcntl
import json
import os
import sys
from contextlib import contextmanager

from lightcycle.domain.pool.spin_ledger import SpinLedger
from lightcycle.ports.spin import SpinPort


def spin_path(root):
    return os.path.join(root, "logs", "spin.json")


def _lock_path(root):
    return os.path.join(root, "logs", "spin.lock")


@contextmanager
def _spin_lock(root):
    os.makedirs(os.path.join(root, "logs"), exist_ok=True)
    fd = os.open(_lock_path(root), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def load(root):
    p = spin_path(root)
    if not os.path.exists(p):
        return SpinLedger()
    try:
        return SpinLedger.from_state(json.loads(open(p).read()))
    except Exception as e:
        sys.stderr.write("warning: could not read spin state %s: %s\n" % (p, e))
        return SpinLedger()


def save(root, ledger):
    os.makedirs(os.path.join(root, "logs"), exist_ok=True)
    p = spin_path(root)
    tmp = "%s.%d.tmp" % (p, os.getpid())
    with open(tmp, "w") as f:
        f.write(json.dumps(ledger.as_dict(), indent=2))
    os.replace(tmp, p)


def update(root, mutate):
    with _spin_lock(root):
        ledger = load(root)
        new_ledger = mutate(ledger)
        save(root, new_ledger)
        return new_ledger


class SpinAdapter(SpinPort):
    def __init__(self, config):
        self._config = config

    def load(self):
        return load(self._config.data_root())

    def update(self, mutate):
        return update(self._config.data_root(), mutate)
