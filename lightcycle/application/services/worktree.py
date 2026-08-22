import os
import time

from lightcycle.application.errors import UseCaseError
from lightcycle.domain.flow.flow import PROJECT_WORKSPACE, SPECS_WORKSPACE
from lightcycle.domain.work import Item, State
from lightcycle.domain.workspace import (
    Branch, Worktree, current_run_index, phase_key, runs_of,
)
from lightcycle.ports.store import ProjectResolutionError


class WorktreeService:
    def __init__(self, store, git, fs, config, flow=None):
        self._store = store
        self._git = git
        self._fs = fs
        self._config = config
        self._flow = flow

    def _item(self, item):
        return Item(item, tuple(self._store.item_artifacts(item)))

    def has_repo(self, item):
        return self._item(item).repo() is not None

    def has_worktree_history(self, item):
        return "branch" in self._item(item).present_types()

    def _active_step(self, item):
        for child in self._store.children(item):
            if getattr(child, "type", None) == "step" and child.state != State.DONE:
                return child
        return None

    def _workspace_node(self, item):
        return self._active_step(item) or self._store.get_node(item)

    def _workspace_of(self, item):
        if self._flow is None:
            return PROJECT_WORKSPACE
        return self._flow.workspace_for_node(self._workspace_node(item)) or PROJECT_WORKSPACE

    def _uses_specs_workspace(self, item):
        return self._workspace_of(item) == SPECS_WORKSPACE

    def _uses_item_repo(self, item):
        return self._workspace_of(item) == PROJECT_WORKSPACE

    def _repo_for_workspace(self, item, workspace):
        if workspace == SPECS_WORKSPACE:
            return self._config.specs_root()
        if workspace == PROJECT_WORKSPACE:
            return self._resolve_repo(self.item_repo(item))
        return self._resolve_repo(workspace)

    def _phase(self, item):
        if self._flow is None:
            return None
        return self._flow.phase_for(self._workspace_node(item))

    def item_repo(self, item):
        repo = self._item(item).repo()
        if repo is None:
            raise UseCaseError("item '%s' has no repo artifact" % item)
        return repo

    def target_repo(self, item):
        return self._repo_for_workspace(item, self._workspace_of(item))

    def _resolve_repo(self, repo):
        try:
            return self._store.resolve_project_path(repo)
        except ProjectResolutionError as e:
            raise UseCaseError(str(e))

    def _recorded_branches(self, item):
        return [(a.label, a.value) for a in self._item(item).artifacts if a.type == "branch"]

    def _target_for_phase(self, item, phase):
        if self._flow is None:
            return self._resolve_repo(self.item_repo(item))
        node = self._store.get_node(item)
        workspace = self._flow.workspace_for_phase(node, phase) or PROJECT_WORKSPACE
        return self._repo_for_workspace(item, workspace)

    def _step_phases(self, item):
        if self._flow is None:
            return []
        return [
            self._flow.phase_for(child)
            for child in self._store.children(item)
            if getattr(child, "type", None) == "step"
        ]

    def _phase_key(self, item):
        return phase_key(self._phase(item), current_run_index(self._step_phases(item)))

    def worktree_path(self, item):
        return Worktree(item, self._phase_key(item)).path_in(self.target_repo(item))

    def item_branch(self, item):
        return self._item(item).artifact_of("branch", label=self._phase(item))

    def _minted_branch(self, item):
        return Branch.for_feature(
            self._store.get_node(item).title, self._config.branch_prefix(),
            ident=item, phase=self._phase_key(item)
        ).name

    def _branch_for(self, item):
        recorded = self.item_branch(item)
        if recorded is None:
            return self._minted_branch(item)
        if current_run_index(self._step_phases(item)) <= 1:
            return recorded
        minted = self._minted_branch(item)
        return recorded if recorded == minted else minted

    def _run_for_phase(self, item, phase):
        return max(1, runs_of(self._step_phases(item), phase))

    def _release_run(self, item, phase, run_index, branch, delete_remote=True):
        if run_index < 1 or branch is None:
            return
        target = self._target_for_phase(item, phase)
        if not self._git.is_git_repo(target):
            return
        path = Worktree(item, phase_key(phase, run_index)).path_in(target)
        self._git.remove_worktree(target, path)
        self._git.delete_branch(target, branch)
        if delete_remote:
            self._git.delete_remote_branch(target, branch)

    def _ensure_branch_artifact(self, item, branch):
        recorded = self.item_branch(item)
        if recorded == branch:
            return
        phase = self._phase(item)
        if recorded is None:
            self._store.add_artifact(item, "branch", branch, label=phase)
            return
        self._release_run(
            item, phase, current_run_index(self._step_phases(item)) - 1, recorded,
            delete_remote=False,
        )
        self._store.replace_artifact(item, "branch", branch, label=phase)

    def ensure(self, item):
        if self._uses_item_repo(item) and not self.has_repo(item):
            return None
        target = self.target_repo(item)
        if not self._git.is_git_repo(target):
            named = self.item_repo(item) if self._uses_item_repo(item) else target
            raise UseCaseError(
                "cannot set up workspace for %s: '%s' is not a git repo at %s"
                % (item, named, target)
            )
        branch = self._branch_for(item)
        path = self.worktree_path(item)
        if self._git.worktree_registered(target, path) and os.path.isdir(path):
            self._ensure_branch_artifact(item, branch)
            return path
        is_new_branch = not self._git.branch_exists(target, branch)
        if is_new_branch:
            if not self._git.sync_to_origin(target):
                raise UseCaseError(
                    "cannot set up workspace for %s: failed to sync '%s' with origin "
                    "(fetch failed, or the local base has diverged)" % (item, target)
                )
            base = self._git.worktree_base(target)
            if base is None:
                raise UseCaseError(
                    "cannot set up workspace for %s: no base branch found in %s" % (item, target)
                )
            add_args = ["worktree", "add", path, "--no-track", "-b", branch, base]
        else:
            add_args = ["worktree", "add", path, branch]
        os.makedirs(self._fs.worktrees_dir(target), exist_ok=True)
        self._fs.ensure_worktrees_ignored(self._git.common_dir(target))
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
            raise UseCaseError(
                "cannot set up workspace for %s: %s" % (item, res.stderr.strip())
            )
        if is_new_branch:
            self._git.git(target, "config", "branch.%s.remote" % branch, "origin")
            self._git.git(target, "config", "branch.%s.merge" % branch,
                          "refs/heads/%s" % branch)
        self._ensure_branch_artifact(item, branch)
        return path

    def sync_specs(self):
        root = self._config.specs_root()
        if not self._git.is_git_repo(root):
            if not self._git.clone(self._config.specs_remote(), root):
                raise UseCaseError(
                    "cannot read spec: failed to clone specs repo '%s' into '%s'"
                    % (self._config.specs_remote(), root)
                )
        if not self._git.sync_to_default_branch(root):
            raise UseCaseError(
                "cannot read spec: failed to sync specs checkout '%s' to the origin default branch "
                "(fetch failed, no default branch found, or the local checkout is dirty/diverged)"
                % root
            )

    def remove(self, item):
        if not self.has_worktree_history(item):
            return
        if not self._uses_specs_workspace(item) and not self.has_repo(item):
            return
        for phase, branch in self._recorded_branches(item):
            self._release_run(item, phase, self._run_for_phase(item, phase), branch)
