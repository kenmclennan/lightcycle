import posixpath
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Worktree:
    item: str
    phase: Optional[str] = None

    def path_in(self, repo_root: str) -> str:
        name = "%s-%s" % (self.item, self.phase) if self.phase else self.item
        return posixpath.join(repo_root, ".worktrees", name)
