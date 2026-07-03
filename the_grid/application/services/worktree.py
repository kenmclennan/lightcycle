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
        return (
            self.story_branch(story)
            or Branch.for_feature(
                self._store.get_task(story).title, self._config.branch_prefix()
            ).name
        )

    def _ensure_branch_artifact(self, story, branch):
        if any(a.type == "branch" for a in self._store.story_artifacts(story)):
            return
        self._store.add_artifact(story, "branch", branch)

    def ensure(self, story):
        target = self.target_repo(story)
        if not self._git.is_git_repo(target):
            return None
        branch = self._branch_for(story)
        path = self.worktree_path(story)
        if self._git.worktree_registered(target, path) and os.path.isdir(path):
            self._ensure_branch_artifact(story, branch)
            return path
        is_new_branch = not self._git.branch_exists(target, branch)
        if is_new_branch:
            base = self._git.worktree_base(target)
            if base is None:
                return None
            add_args = ["worktree", "add", path, "--no-track", "-b", branch, base]
        else:
            add_args = ["worktree", "add", path, branch]
        os.makedirs(self._fs.worktrees_dir(), exist_ok=True)
        self._fs.ensure_worktrees_ignored()
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
        if is_new_branch:
            self._git.git(target, "config", "branch.%s.remote" % branch, "origin")
            self._git.git(target, "config", "branch.%s.merge" % branch,
                          "refs/heads/%s" % branch)
        self._ensure_branch_artifact(story, branch)
        return path

    def remove(self, story):
        target = self.target_repo(story)
        if not self._git.is_git_repo(target):
            return
        branch = self._branch_for(story)
        self._git.remove_worktree(target, self.worktree_path(story))
        self._git.delete_branch(target, branch)
        self._git.delete_remote_branch(target, branch)
