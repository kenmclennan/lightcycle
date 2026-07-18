import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Worktree:
    item: str
    phase: str = None

    def path_in(self, repo_root: str) -> str:
        name = "%s-%s" % (self.item, self.phase) if self.phase else self.item
        return os.path.join(repo_root, ".worktrees", name)

    @staticmethod
    def is_lock_contention(stderr: str) -> bool:
        t = (stderr or "").lower()
        return (
            "could not lock" in t
            or "already locked" in t
            or "index.lock" in t
            or ".lock': file exists" in t
        )
