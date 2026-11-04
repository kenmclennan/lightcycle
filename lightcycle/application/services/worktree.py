import sys

from lightcycle.application.errors import UseCaseError
from lightcycle.application.setup.project_registry import ProjectRegistry
from lightcycle.application.work.stack_runs import StackRuns
from lightcycle.domain.flow.flow import PROJECT_WORKSPACE
from lightcycle.domain.runs import RunState, pass_number
from lightcycle.domain.work import State
from lightcycle.domain.workspace import Branch, Worktree
from lightcycle.ports.git import GitReadError
from lightcycle.ports.store import ProjectResolutionError


STACK_BASE = "stack-base"
STACK_BRANCH_RETAINED_LABEL = "stack-branch-retained"


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
        slice = getattr(node, "slice", 0)
        run = self._store.current_run(item, phase, slice)
        if run is not None or not create:
            return run
        if slice > 0:
            raise UseCaseError(
                "cannot set up workspace for %s: slice %d has no run in phase %s"
                % (item, slice, phase)
            )
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
        if run.phase is None:
            return None if run.round <= 1 else "r%d" % run.round
        n = pass_number(run.pass_id)
        key = run.phase if n <= 1 else "%s-%d" % (run.phase, n)
        if run.slice > 0:
            key = "%s-s%d" % (key, run.slice)
        return key if run.round <= 1 else "%s-r%d" % (key, run.round)

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

    def target_for_run(self, run):
        return self._target_for_phase(run.item, run.phase)

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
        if delete_remote and self._retained_for_children(run):
            self._store.label_add(run.item, STACK_BRANCH_RETAINED_LABEL)
        elif delete_remote:
            outcome = self._git.delete_remote_branch(target, run.branch)
            if outcome is not None and not outcome.ok:
                print(
                    "warning: remote branch delete failed for %s: %s"
                    % (run.branch, outcome.detail),
                    file=sys.stderr,
                )

    def _retained_for_children(self, run):
        if self._flow is None:
            return False
        if not any(c.state != State.DONE for c in self._stacked_children(run.item)):
            return False
        stack_run = StackRuns(self._store, self._flow).run_of(run.item)
        return stack_run is not None and stack_run.id == run.id

    def _stacked_children(self, item):
        return self._store.items_stacked_on(item)

    def release_interrupted(self, run):
        if run is None or run.state == RunState.OPEN or run.branch is None:
            return False
        target = self._target_for_phase(run.item, run.phase)
        if not self._git.is_git_repo(target):
            return False
        path = self.path_for_run(run)
        if not (self._git.worktree_registered(target, path)
                or self._git.branch_exists(target, run.branch)):
            return False
        self.release_run(run)
        return True

    def _ensure_branch_artifact(self, node, branch):
        run = self._run(node, create=True)
        if run.branch == branch:
            return
        self._store.set_branch(run.id, branch)

    def _slice_base(self, node, item, target):
        run = self._run(node)
        if run is None or run.base_slice is None:
            return False
        siblings = [
            r for r in self._store.runs_of(item, run.pass_id)
            if r.phase == run.phase and r.slice == run.base_slice
        ]
        base_run = siblings[-1] if siblings else None
        if base_run is None or base_run.state == RunState.MERGED or not base_run.branch:
            return None
        if not self._git.remote_branch_exists(target, base_run.branch):
            raise UseCaseError(
                "cannot set up workspace for %s: the base slice %s's branch %s no longer "
                "exists on origin" % (item, base_run.slice_name, base_run.branch)
            )
        return "origin/" + base_run.branch

    def _stacked_base(self, node, item, target):
        if self._flow is None or not self._uses_item_repo(node):
            return None
        if getattr(node, "slice", 0) > 0:
            sliced = self._slice_base(node, item, target)
            if sliced is not False:
                return sliced
        parent_id = self._item(item).stacks_on
        if not parent_id:
            return None
        parent = self._item(parent_id)
        if parent.state == State.DONE or parent.repo != self._item(item).repo:
            return None
        run = StackRuns(self._store, self._flow).run_of(parent_id)
        if run is None or not run.pr:
            return None
        if not self._git.remote_branch_exists(target, run.branch):
            raise UseCaseError(
                "cannot set up workspace for %s: the parent %s's branch %s no longer exists "
                "on origin" % (item, parent_id, run.branch)
            )
        return "origin/" + run.branch

    def _stack_sha(self, target, stacked):
        if not stacked:
            return None
        try:
            return self._git.ref_sha(target, stacked)
        except GitReadError:
            return None

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
            stacked = self._stacked_base(node, item, target)
            base = stacked or base
            stack_sha = self._stack_sha(target, stacked)
        else:
            base = None
            stack_sha = None
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
            if stack_sha:
                self._store.replace_artifact(item, STACK_BASE, stack_sha, internal=True)
        return path

    def context_path(self):
        return self._resolve_repo(self._config.context_artifact_project())

    def sync_context(self):
        identity = self._config.context_artifact_project()
        project = self._store.get_project(identity)
        if project is None or not project.local_path:
            raise UseCaseError(
                "cannot read spec: no '%s' project registered - run `lc init`"
                % identity
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

    def _run_findings(self, item, run, proven_merged, fetched, check_dirty=True):
        target = self._target_for_phase(item, run.phase)
        if not self._git.is_git_repo(target):
            return []
        findings = self._dirty_findings(target, self.path_for_run(run)) if check_dirty else []
        if proven_merged:
            return findings
        if target not in fetched:
            fetched.add(target)
            self._git.fetch_origin(target)
        return findings + self._unmerged_findings(target, run.branch)

    def teardown_refusals(self, item, merged_prs=frozenset()):
        return self._refusals(item, merged_prs, check_dirty=True)

    def unmerged_refusals(self, item, merged_prs=frozenset()):
        return self._refusals(item, merged_prs, check_dirty=False)

    def _refusals(self, item, merged_prs, check_dirty):
        findings = []
        fetched = set()
        for run in self._releasable_runs(item):
            proven = run.state == RunState.MERGED or bool(run.pr and run.pr in merged_prs)
            findings += self._run_findings(item, run, proven, fetched, check_dirty)
        return findings

    def pass_release_refusals(self, item, runs):
        releasable = {run.id for run in self._releasable_runs(item)}
        findings = []
        fetched = set()
        for run in runs:
            if run.id not in releasable:
                continue
            findings += self._run_findings(item, run, run.state == RunState.MERGED, fetched)
        return findings

    def phase_release_refusals(self, run):
        if not run.branch:
            return []
        return self._run_findings(run.item, run, True, set())

    def _dirty_findings(self, target, path):
        try:
            if not self._git.worktree_registered(target, path):
                return []
        except GitReadError as e:
            return ["could not tell whether worktree %s is registered: %s" % (path, e)]
        try:
            paths = self._git.uncommitted_paths(path)
        except GitReadError as e:
            return ["could not read the state of worktree %s: %s" % (path, e)]
        if not paths:
            return []
        return ["worktree %s has uncommitted paths: %s" % (path, ", ".join(paths))]

    def _unmerged_findings(self, target, branch):
        try:
            if not self._git.branch_exists(target, branch):
                return []
        except GitReadError as e:
            return ["could not tell whether branch %s exists: %s" % (branch, e)]
        base = self._git.default_ref(target) or self._git.worktree_base(target)
        if base is None:
            return ["branch %s has no base branch to compare against in %s" % (branch, target)]
        try:
            shas = self._git.commits_beyond(target, base, branch)
        except GitReadError as e:
            return ["could not read the commits of branch %s: %s" % (branch, e)]
        if not shas:
            return []
        return ["branch %s has %d commit(s) beyond %s that are not merged" % (branch, len(shas), base)]

    def remove(self, item):
        failures = []
        for run in self._releasable_runs(item):
            try:
                self.release_run(run)
            except GitReadError as e:
                failures.append(str(e))
        if failures:
            raise GitReadError("; ".join(failures))
