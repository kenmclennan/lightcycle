import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Worktree:
    story: str

    def path_in(self, worktrees_dir: str) -> str:
        return os.path.join(worktrees_dir, self.story)

    @staticmethod
    def is_lock_contention(stderr: str) -> bool:
        t = (stderr or "").lower()
        return (
            "could not lock" in t
            or "already locked" in t
            or "index.lock" in t
            or ".lock': file exists" in t
        )
