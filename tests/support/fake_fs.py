class FakeFs:
    def __init__(self, metas=None, files=None, dirs=None):
        self._metas = metas or {}
        self._files = files or {}
        self._dirs = dirs or {}

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

    def read_bytes(self, path):
        return self._files.get(path)

    def list_dir(self, path):
        return sorted(self._dirs.get(path, []))

    def ensure_logs_dir(self):
        return "/tmp/fake-logs"

    def ensure_worktrees_ignored(self):
        pass
