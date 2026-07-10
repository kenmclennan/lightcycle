import os

from lightcycle.adapters import frontmatter
from lightcycle.ports.fs import FsPort


def _roots(roots):
    return roots if isinstance(roots, (list, tuple)) else [roots]


def step_roles(roots):
    names, seen = [], set()
    for root in _roots(roots):
        adir = os.path.join(root, "steps")
        if not os.path.isdir(adir):
            continue
        for f in os.listdir(adir):
            role = f[:-3]
            if f.endswith(".md") and role not in seen:
                seen.add(role)
                names.append(role)
    return sorted(names)


def read_md(roots, relpath):
    for root in _roots(roots):
        path = os.path.join(root, relpath)
        if os.path.exists(path):
            with open(path) as f:
                text = f.read()
            meta, body = frontmatter.split_frontmatter(text)
            return {"meta": meta, "body": body, "path": path}
    return None


def parse_step(roots, role):
    return read_md(roots, os.path.join("steps", "%s.md" % role))


def workflow_text(roots, name):
    for root in _roots(roots):
        path = os.path.join(root, "workflows", "%s.md" % name)
        if os.path.exists(path):
            with open(path) as f:
                return f.read()
    return None


def worktrees_dir(root):
    return os.path.join(root, ".worktrees")


def store_ready(root):
    return os.path.exists(os.path.join(root, "store.db"))


def read_bytes(path):
    if not path or not os.path.exists(path):
        return None
    with open(path, "rb") as f:
        return f.read()


def list_dir(path):
    if not os.path.isdir(path):
        return []
    return sorted(e.name for e in os.scandir(path) if e.is_dir())


def ensure_override_dirs(root):
    for name in ("steps", "workflows"):
        os.makedirs(os.path.join(root, name), exist_ok=True)


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

    def _search(self, project=None):
        roots = []
        if project:
            roots.append(os.path.join(self._config.projects_root(), project, ".lightcycle"))
        roots.append(self._config.data_root())
        roots.append(self._config.library_root())
        return roots

    def step_roles(self, project=None):
        return step_roles(self._search(project))

    def read_md(self, relpath, project=None):
        return read_md(self._search(project), relpath)

    def parse_step(self, role, project=None):
        return parse_step(self._search(project), role)

    def workflow_text(self, name, project=None):
        return workflow_text(self._search(project), name)

    def worktrees_dir(self, root):
        return worktrees_dir(root)

    def store_ready(self):
        return store_ready(self._config.data_root())

    def read_bytes(self, path):
        return read_bytes(path)

    def list_dir(self, path):
        return list_dir(path)

    def ensure_logs_dir(self):
        return ensure_logs_dir(self._config.data_root())

    def ensure_override_dirs(self):
        return ensure_override_dirs(self._config.data_root())

    def ensure_worktrees_ignored(self, root):
        return ensure_worktrees_ignored(root)
