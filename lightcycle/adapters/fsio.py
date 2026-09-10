import os

from lightcycle.ports.fs import FsPort

DB_FILENAME = "store.db"


def worktrees_dir(root):
    return os.path.join(root, ".worktrees")


def store_ready(root):
    return os.path.exists(os.path.join(root, DB_FILENAME))


def read_bytes(path):
    if not path or not os.path.exists(path):
        return None
    with open(path, "rb") as f:
        return f.read()


def exists(path):
    return bool(path) and os.path.exists(path)


def list_dir(path):
    if not os.path.isdir(path):
        return []
    return sorted(e.name for e in os.scandir(path) if e.is_dir())


def ensure_logs_dir(root):
    d = os.path.join(root, "logs")
    os.makedirs(d, exist_ok=True)
    return d


def ensure_worktrees_ignored(git_dir):
    info_dir = os.path.join(git_dir, "info")
    os.makedirs(info_dir, exist_ok=True)
    exclude = os.path.join(info_dir, "exclude")
    line = ".worktrees/"
    existing = ""
    if os.path.exists(exclude):
        with open(exclude) as f:
            existing = f.read()
    if line in (l.strip() for l in existing.splitlines()):
        return
    with open(exclude, "a") as f:
        if existing and not existing.endswith("\n"):
            f.write("\n")
        f.write(line + "\n")


class FsAdapter(FsPort):
    def __init__(self, config):
        self._config = config

    def worktrees_dir(self, root):
        return worktrees_dir(root)

    def store_ready(self):
        return store_ready(self._config.data_root())

    def read_bytes(self, path):
        return read_bytes(path)

    def exists(self, path):
        return exists(path)

    def list_dir(self, path):
        return list_dir(path)

    def ensure_logs_dir(self):
        return ensure_logs_dir(self._config.data_root())

    def ensure_worktrees_ignored(self, git_dir):
        return ensure_worktrees_ignored(git_dir)
