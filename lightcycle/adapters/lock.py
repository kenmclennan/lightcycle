import fcntl
import os

from lightcycle.adapters.workers import pid_alive
from lightcycle.ports.lock import LockAcquisition, RunLockPort


def lock_path(root):
    return os.path.join(root, ".lc-run.pid")


def _read_pid(path):
    try:
        with open(path) as f:
            raw = f.read().strip()
        return int(raw) if raw else None
    except (OSError, ValueError):
        return None


ACQUIRE_ATTEMPTS = 3


def _locked_the_live_file(fd, path):
    try:
        return os.fstat(fd).st_ino == os.stat(path).st_ino
    except OSError:
        return False


def acquire(root):
    path = lock_path(root)
    for _ in range(ACQUIRE_ATTEMPTS):
        fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            return False, _read_pid(path), None
        if not _locked_the_live_file(fd, path):
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
            continue
        my_pid = os.getpid()
        os.ftruncate(fd, 0)
        os.write(fd, str(my_pid).encode())
        os.fsync(fd)
        return True, my_pid, fd
    return False, _read_pid(path), None


def release(root, fd):
    if fd is None:
        return
    try:
        os.ftruncate(fd, 0)
        os.fsync(fd)
    except OSError:
        pass
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def holder_pid(root):
    pid = _read_pid(lock_path(root))
    return pid if pid is not None and pid_alive(pid) else None


def is_running(root):
    return holder_pid(root) is not None


class RunLockAdapter(RunLockPort):
    def __init__(self, config):
        self._config = config
        self._fd = None

    def acquire(self):
        acquired, pid, fd = acquire(self._config.data_root())
        if acquired:
            self._fd = fd
        return LockAcquisition(acquired=acquired, holder_pid=pid)

    def release(self):
        release(self._config.data_root(), self._fd)
        self._fd = None

    def is_running(self):
        return is_running(self._config.data_root())

    def holder_pid(self):
        return holder_pid(self._config.data_root())
