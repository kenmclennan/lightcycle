import os
import sys
import time

from lightcycle.domain.work import Item
from lightcycle.domain.workspace import Branch, Worktree


class WorktreeService:
    def __init__(self, store, git, fs, config):
        self._store = store
        self._git = git
        self._fs = fs
        self._config = config

    def _item(self, item):
        return Item(item, tuple(self._store.item_artifacts(item)))

    def item_repo(self, item):
        return self._item(item).repo(os.path.basename(self._config.engine_root()))

    def target_repo(self, item):
        return os.path.join(self._config.projects_root(), self.item_repo(item))

    def worktree_path(self, item):
        return Worktree(item).path_in(self.target_repo(item))

    def item_branch(self, item):
        return self._item(item).branch()

    def _branch_for(self, item):
        return (
            self.item_branch(item)
            or Branch.for_feature(
                self._store.get_node(item).title, self._config.branch_prefix(), ident=item
            ).name
        )

    def _ensure_branch_artifact(self, item, branch):
        if any(a.type == "branch" for a in self._store.item_artifacts(item)):
            return
        self._store.add_artifact(item, "branch", branch)

    def ensure(self, item):
        target = self.target_repo(item)
        if not self._git.is_git_repo(target):
            return None
        branch = self._branch_for(item)
        path = self.worktree_path(item)
        if self._git.worktree_registered(target, path) and os.path.isdir(path):
            self._ensure_branch_artifact(item, branch)
            return path
        is_new_branch = not self._git.branch_exists(target, branch)
        if is_new_branch:
            base = self._git.worktree_base(target)
            if base is None:
                return None
            add_args = ["worktree", "add", path, "--no-track", "-b", branch, base]
        else:
            add_args = ["worktree", "add", path, branch]
        os.makedirs(self._fs.worktrees_dir(target), exist_ok=True)
        self._fs.ensure_worktrees_ignored(target)
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
        self._ensure_branch_artifact(item, branch)
        return path

    def remove(self, item):
        target = self.target_repo(item)
        if not self._git.is_git_repo(target):
            return
        branch = self._branch_for(item)
        self._git.remove_worktree(target, self.worktree_path(item))
        self._git.delete_branch(target, branch)
        self._git.delete_remote_branch(target, branch)
