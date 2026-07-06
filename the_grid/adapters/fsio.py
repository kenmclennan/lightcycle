import os

from the_grid.adapters import frontmatter
from the_grid.ports.fs import FsPort


def step_roles(root):
    adir = os.path.join(root, "steps")
    if not os.path.isdir(adir):
        return []
    return sorted(f[:-3] for f in os.listdir(adir) if f.endswith(".md"))


def read_md(root, relpath):
    path = os.path.join(root, relpath)
    if not os.path.exists(path):
        return None
    with open(path) as f:
        text = f.read()
    meta, body = frontmatter.split_frontmatter(text)
    return {"meta": meta, "body": body, "path": path}


def parse_step(root, role):
    return read_md(root, os.path.join("steps", "%s.md" % role))


def workflow_text(root, name):
    path = os.path.join(root, "workflows", "%s.md" % name)
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return f.read()


def worktrees_dir(root):
    return os.path.join(root, ".worktrees")


def store_ready(root):
    return os.path.exists(os.path.join(root, ".grid.db"))


def read_bytes(path):
    if not path or not os.path.exists(path):
        return None
    with open(path, "rb") as f:
        return f.read()


def list_dir(path):
    if not os.path.isdir(path):
        return []
    return sorted(e.name for e in os.scandir(path) if e.is_dir())


def ensure_logs_dir(root):
    d = os.path.join(root, "logs")
    os.makedirs(d, exist_ok=True)
    return d


def ensure_worktrees_ignored(root):
    gi = os.path.join(root, ".gitignore")
    line = ".worktrees/"
    existing = ""
    if os.path.exists(gi):
        with open(gi) as f:
            existing = f.read()
    if line in (l.strip() for l in existing.splitlines()):
        return
    with open(gi, "a") as f:
        if existing and not existing.endswith("\n"):
            f.write("\n")
        f.write(line + "\n")


class FsAdapter(FsPort):
    def __init__(self, config):
        self._config = config

    def step_roles(self):
        return step_roles(self._config.grid_root())

    def read_md(self, relpath):
        return read_md(self._config.grid_root(), relpath)

    def parse_step(self, role):
        return parse_step(self._config.grid_root(), role)

    def workflow_text(self, name):
        return workflow_text(self._config.grid_root(), name)

    def worktrees_dir(self):
        return worktrees_dir(self._config.grid_root())

    def store_ready(self):
        return store_ready(self._config.grid_root())

    def read_bytes(self, path):
        return read_bytes(path)

    def list_dir(self, path):
        return list_dir(path)

    def ensure_logs_dir(self):
        return ensure_logs_dir(self._config.grid_root())

    def ensure_worktrees_ignored(self):
        return ensure_worktrees_ignored(self._config.grid_root())
