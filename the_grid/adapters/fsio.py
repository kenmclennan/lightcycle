"""Filesystem IO: step files and well-known dirs under the engine root.

The engine root and the config file are owned by Config; these functions take an
explicit `root` (Config.grid_root()) and do no environment reads.
"""
import os

from the_grid.adapters import frontmatter
from the_grid.ports.fs import FsPort


def step_roles(root):
    adir = os.path.join(root, "steps")
    if not os.path.isdir(adir):
        return []
    return sorted(f[:-3] for f in os.listdir(adir) if f.endswith(".md"))


def read_md(root, relpath):
    """Read a markdown file under the grid root; return {meta, body, path} or None."""
    path = os.path.join(root, relpath)
    if not os.path.exists(path):
        return None
    with open(path) as f:
        text = f.read()
    meta, body = frontmatter.split_frontmatter(text)
    return {"meta": meta, "body": body, "path": path}


def parse_step(root, role):
    """Read a step file steps/<role>.md; return {meta, body, path} or None."""
    return read_md(root, os.path.join("steps", "%s.md" % role))


def worktrees_dir(root):
    return os.path.join(root, ".worktrees")


def store_ready(root):
    return os.path.isdir(os.path.join(root, ".beads"))


def read_bytes(path):
    """Read a file's bytes at an absolute path, or None if it does not exist."""
    if not path or not os.path.exists(path):
        return None
    with open(path, "rb") as f:
        return f.read()


def list_dir(path):
    """Sorted names of the subdirectories of path (empty if path is not a dir)."""
    if not os.path.isdir(path):
        return []
    return sorted(e.name for e in os.scandir(path) if e.is_dir())


def ensure_logs_dir(root):
    d = os.path.join(root, "logs")
    os.makedirs(d, exist_ok=True)
    return d


class FsAdapter(FsPort):
    """FsPort rooted at Config.grid_root()."""

    def __init__(self, config):
        self._config = config

    def step_roles(self):
        return step_roles(self._config.grid_root())

    def read_md(self, relpath):
        return read_md(self._config.grid_root(), relpath)

    def parse_step(self, role):
        return parse_step(self._config.grid_root(), role)

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
