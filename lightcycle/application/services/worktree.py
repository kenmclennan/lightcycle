from lightcycle.application.errors import UseCaseError
from lightcycle.application.setup.project_registry import ProjectRegistry
from lightcycle.domain.flow.flow import PROJECT_WORKSPACE, SPECS_WORKSPACE
from lightcycle.domain.runs import pass_number
from lightcycle.domain.workspace import Branch, Worktree
from lightcycle.ports.git import GitReadError
from lightcycle.ports.store import ProjectResolutionError


class WorktreeService:
    def __init__(self, store, git, fs, config, flow=None, scaffold=None):
        self._store = store
        self._git = git
        self._fs = fs
        self._config = config
        self._flow = flow
        self._scaffold = scaffold

    def _item(self, item):
        return self._store.get_item(item)

    def has_repo(self, item):
        return self._item(item).repo is not None

    def has_worktree_history(self, item):
        return any(r.branch for r in self._store.runs_of(item))

    @staticmethod
    def _item_of(node):
        return getattr(node, "item", None) or node.id

    def _workspace_of(self, node):
        if self._flow is None:
            return PROJECT_WORKSPACE
        return self._flow.workspace_for_node(node) or PROJECT_WORKSPACE

    def _uses_item_repo(self, node):
        return self._workspace_of(node) == PROJECT_WORKSPACE

    def _repo_for_workspace(self, item, workspace):
        if workspace == PROJECT_WORKSPACE:
            return self._resolve_repo(self.item_repo(item))
        return self._resolve_repo(workspace)

    def _phase(self, node):
        if self._flow is None:
            return None
        return self._flow.phase_for(node)

    def item_repo(self, item):
        repo = self._item(item).repo
        if repo is None:
            raise UseCaseError("item '%s' has no repo artifact" % item)
        return repo

    def target_repo(self, node):
        return self._repo_for_workspace(self._item_of(node), self._workspace_of(node))

    def _resolve_repo(self, repo):
        try:
            return ProjectRegistry(self._store).resolve_path(repo)
        except ProjectResolutionError as e:
            raise UseCaseError(str(e))

    def _run(self, node, create=False):
        item = self._item_of(node)
        phase = self._phase(node)
        run = self._store.current_run(item, phase)
        if run is not None or not create:
            return run
        current = self._store.current_pass(item)
        pid = current.id if current else self._store.open_pass(item)
        return self._store.get_run(self._store.open_run(item, pid, phase))

    def _workspace_for_phase(self, item, phase):
        if self._flow is None:
            return PROJECT_WORKSPACE
        node = self._store.get_node(item)
        return self._flow.workspace_for_phase(node, phase) or PROJECT_WORKSPACE

    def _target_for_phase(self, item, phase):
        return self._repo_for_workspace(item, self._workspace_for_phase(item, phase))

    def _phase_key(self, node):
        run = self._run(node)
        return self._key_for(run) if run else self._phase(node)

    @staticmethod
    def _key_for(run):
        n = pass_number(run.pass_id)
        if run.phase is None or n <= 1:
            return run.phase
        return "%s-%d" % (run.phase, n)

    def worktree_path(self, node):
        return Worktree(self._item_of(node), self._phase_key(node)).path_in(self.target_repo(node))

    def item_branch(self, node):
        run = self._run(node)
        return run.branch if run else None

    def _minted_branch(self, node):
        item = self._item_of(node)
        return Branch.for_feature(
            self._store.get_node(item).title, self._config.branch_prefix(),
            ident=item, phase=self._phase_key(node)
        ).name

    def _branch_for(self, node):
        return self.item_branch(node) or self._minted_branch(node)

    def path_for_run(self, run):
        return Worktree(run.item, self._key_for(run)).path_in(self._target_for_phase(run.item, run.phase))

    def release_run(self, run, delete_remote=True):
        if run is None or run.branch is None:
            return
        target = self._target_for_phase(run.item, run.phase)
        if not self._git.is_git_repo(target):
            return
        path = self.path_for_run(run)
        self._git.remove_worktree(target, path)
        self._git.delete_branch(target, run.branch)
        if delete_remote:
            self._git.delete_remote_branch(target, run.branch)

    def _ensure_branch_artifact(self, node, branch):
        run = self._run(node, create=True)
        if run.branch == branch:
            return
        self._store.set_branch(run.id, branch)

    def ensure(self, node):
        item = self._item_of(node)
        if self._uses_item_repo(node) and not self.has_repo(item):
            return None
        target = self.target_repo(node)
        if not self._git.is_git_repo(target):
            named = self.item_repo(item) if self._uses_item_repo(node) else target
            raise UseCaseError(
                "cannot set up workspace for %s: '%s' is not a git repo at %s"
                % (item, named, target)
            )
        branch = self._branch_for(node)
        self._ensure_branch_artifact(node, branch)
        path = self.worktree_path(node)
        try:
            registered = self._git.worktree_registered(target, path)
        except GitReadError:
            registered = False
        if registered and self._scaffold.is_dir(path):
            return path
        try:
            is_new_branch = not self._git.branch_exists(target, branch)
        except GitReadError:
            is_new_branch = True
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
        else:
            base = None
        self._scaffold.make_dir(self._fs.worktrees_dir(target))
        try:
            common = self._git.common_dir(target)
        except GitReadError as e:
            raise UseCaseError("cannot set up workspace for %s: %s" % (item, e))
        self._fs.ensure_worktrees_ignored(common)
        retries = self._config.worktree_retries()
        backoff = self._config.worktree_retry_sleep()
        outcome = self._git.add_worktree(target, path, branch, base, retries, backoff)
        if not outcome.ok:
            raise UseCaseError("cannot set up workspace for %s: %s" % (item, outcome.detail))
        if is_new_branch:
            self._git.set_branch_upstream(target, branch)
        return path

    def specs_path(self):
        return self._resolve_repo(SPECS_WORKSPACE)

    def sync_specs(self):
        project = self._store.get_project(SPECS_WORKSPACE)
        if project is None or not project.local_path:
            raise UseCaseError(
                "cannot read spec: no '%s' project registered - run `lc init`"
                % SPECS_WORKSPACE
            )
        root = project.local_path
        if not self._git.is_git_repo(root):
            if not project.remote or not self._git.clone(project.remote, root):
                raise UseCaseError(
                    "cannot read spec: failed to clone specs repo '%s' into '%s'"
                    % (project.remote, root)
                )
        if not self._git.sync_to_default_branch(root):
            raise UseCaseError(
                "cannot read spec: failed to sync specs checkout '%s' to the origin default branch "
                "(fetch failed, no default branch found, or the local checkout is dirty/diverged)"
                % root
            )

    def _releasable_runs(self, item):
        branched = [run for run in self._store.runs_of(item) if run.branch]
        if not branched:
            return []
        has_repo = self.has_repo(item)
        return [
            run
            for run in branched
            if has_repo or self._workspace_for_phase(item, run.phase) != PROJECT_WORKSPACE
        ]

    def worktrees_of(self, item):
        return [
            (self._target_for_phase(item, run.phase), self.path_for_run(run))
            for run in self._releasable_runs(item)
        ]

    def remove(self, item):
        for run in self._releasable_runs(item):
            self.release_run(run)
