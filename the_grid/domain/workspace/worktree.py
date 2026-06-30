"""Worktree: a story's isolated git working tree (a value object)."""
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Worktree:
    story: str

    def path_in(self, worktrees_dir: str) -> str:
        return os.path.join(worktrees_dir, self.story)

    @staticmethod
    def is_lock_contention(stderr: str) -> bool:
        """A `git worktree add` failure that is transient lock contention from a
        concurrent peer (worth retrying), not a real error. Several pool workers
        adding worktrees against one target repo at once race on git's
        `.git/worktrees` lock."""
        t = (stderr or "").lower()
        return ("could not lock" in t or "already locked" in t
                or "index.lock" in t or ".lock': file exists" in t)
