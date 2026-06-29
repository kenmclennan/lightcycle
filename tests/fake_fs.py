"""FakeFs: in-memory FsPort for tests. Holds step metas, no filesystem."""


class FakeFs:

    def __init__(self, metas=None):
        self._metas = metas or {}  # {role: meta dict}

    def step_roles(self):
        return sorted(self._metas)

    def parse_step(self, role):
        if role not in self._metas:
            return None
        return {"meta": self._metas[role] or {}, "body": "", "path": role}

    def read_md(self, relpath):
        return None

    def worktrees_dir(self):
        return "/tmp/fake-worktrees"

    def store_ready(self):
        return True
