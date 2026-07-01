"""WorktreeService: the per-story git worktree lifecycle.

A worker never mutates the primary tree - each story gets its own worktree on a
feature-named branch in the target repo (the engine itself by default, or the
repo named in the story's `repo` artifact). This service owns resolving that
target, creating/reusing the worktree, and tearing it down on close.
"""
import os
import sys
import time

from the_grid.domain.work import Story
from the_grid.domain.workspace import Branch, Worktree


class WorktreeService:

    def __init__(self, store, git, fs, config):
        self._store = store
        self._git = git
        self._fs = fs
        self._config = config

    def _story(self, story):
        return Story(story, tuple(self._store.story_artifacts(story)))

    def story_repo(self, story):
        return self._story(story).repo(os.path.basename(self._config.grid_root()))

    def target_repo(self, story):
        return os.path.join(self._config.projects_root(), self.story_repo(story))

    def worktree_path(self, story):
        return Worktree(story).path_in(self._fs.worktrees_dir())

    def story_branch(self, story):
        return self._story(story).branch()

    def _branch_for(self, story):
        return self.story_branch(story) or Branch.for_feature(
            self._store.get_task(story).title, self._config.branch_prefix()).name

    def _ensure_branch_artifact(self, story, branch):
        if any(a.type == "branch" for a in self._store.story_artifacts(story)):
            return
        self._store.add_artifact(story, "branch", branch)

    def ensure(self, story):
        """Create (or reuse) the per-story worktree. Returns the workspace path, or
        None when no isolated tree can be made (not a git repo, or no origin/main to
        branch from). Idempotent."""
        target = self.target_repo(story)
        if not self._git.is_git_repo(target):
            return None
        branch = self._branch_for(story)
        path = self.worktree_path(story)
        if self._git.worktree_registered(target, path) and os.path.isdir(path):
            self._ensure_branch_artifact(story, branch)
            return path
        if self._git.branch_exists(target, branch):
            add_args = ["worktree", "add", path, branch]
        else:
            base = self._git.worktree_base(target)
            if base is None:
                return None
            add_args = ["worktree", "add", path, "-b", branch, base]
        os.makedirs(self._fs.worktrees_dir(), exist_ok=True)
        self._fs.ensure_worktrees_ignored()
        # Several pool workers may add worktrees against one target repo at once and
        # race on git's `.git/worktrees` lock; the add is idempotent, so retry the
        # transient lock failure with a short backoff before giving up.
        retries = self._config.worktree_retries()
        backoff = self._config.worktree_retry_sleep()
        self._git.git(target, "worktree", "prune")
        res = self._git.git(target, *add_args)
        while res.returncode != 0 and retries > 0 and Worktree.is_lock_contention(res.stderr):
            retries -= 1
            time.sleep(backoff)
            self._git.git(target, "worktree", "prune")
            res = self._git.git(target, *add_args)
        if res.returncode != 0:
            sys.stderr.write(res.stderr)
            return None
        self._ensure_branch_artifact(story, branch)
        return path

    def remove(self, story):
        """Tear down the story's worktree and delete its branch (on close)."""
        target = self.target_repo(story)
        if not self._git.is_git_repo(target):
            return
        self._git.remove_worktree(target, self.worktree_path(story))
        self._git.delete_branch(target, self._branch_for(story))
