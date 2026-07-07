import os

from lightcycle.adapters.workers import pid_alive
from lightcycle.ports.lock import RunLockPort


def lock_path(root):
    return os.path.join(root, ".lc-run.pid")


def _read_pid(path):
    try:
        with open(path) as f:
            raw = f.read().strip()
        return int(raw) if raw else None
    except (OSError, ValueError):
        return None


def acquire(root):
    path = lock_path(root)
    my_pid = os.getpid()
    while True:
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            holder_pid = _read_pid(path)
            if holder_pid is not None and pid_alive(holder_pid):
                return False, holder_pid
            try:
                os.remove(path)
            except OSError:
                pass
            continue
        with os.fdopen(fd, "w") as f:
            f.write(str(my_pid))
        return True, my_pid


def release(root):
    path = lock_path(root)
    if _read_pid(path) == os.getpid():
        try:
            os.remove(path)
        except OSError:
            pass


class RunLockAdapter(RunLockPort):
    def __init__(self, config):
        self._config = config

    def acquire(self):
        return acquire(self._config.data_root())

    def release(self):
        release(self._config.data_root())
