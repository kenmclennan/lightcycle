import os
import shutil
import tempfile
import unittest

from lightcycle.application.errors import UseCaseError
from lightcycle.application.services.worktree import WorktreeService
from lightcycle.ports.git import GitReadError
from tests.support.fake_fs import FakeFs
from tests.support.fake_github import FakeGitHub
from tests.support.fake_store import FakeStore


class _Cfg:
    def __init__(self, projects_root, engine_root="lightcycle", specs_root="/specs",
                 specs_remote=None):
        self._projects_root = projects_root
        self._engine_root = engine_root
        self._specs_root = specs_root
        self._specs_remote = specs_remote

    def projects_root(self):
        return self._projects_root

    def specs_root(self):
        return self._specs_root

    def specs_remote(self):
        return self._specs_remote

    def engine_root(self):
        return self._engine_root

    def worktree_retries(self):
        return 0

    def worktree_retry_sleep(self):
        return 0

    def branch_prefix(self):
        return "feat"


class _FakeFlow:
    def __init__(self, workspace="project"):
        self._workspace = workspace

    def workflow_for(self, node):
        return "spec" if self._workspace == "specs" else "standard"

    def project_for(self, node):
        return None

    def load_graph(self, name=None):
        return _Graph(self._workspace)

    def workspace_for_node(self, node):
        return self._workspace

    def phase_for(self, node):
        return "spec" if self._workspace == "specs" else "code"

    def workspace_for_phase(self, node, phase):
        return self._workspace


class _PhaseFlow:
    def __init__(self, phase):
        self._phase = phase

    def workflow_for(self, node):
        return "standard"

    def load_graph(self, name=None):
        return _Graph("project")

    def workspace_for_node(self, node):
        return "project"

    def phase_for(self, node):
        return self._phase

    def workspace_for_phase(self, node, phase):
        return "project"


class _Graph:
    def __init__(self, workspace):
        self.workspace = workspace


class _GitResult:
    def __init__(self, returncode=0, stderr=""):
        self.returncode = returncode
        self.stderr = stderr


class _FakeGit:
    def __init__(self, git_repos=(), sync_result=True, base=None, registered=(), branches=(),
                 clone_result=True, sync_default_result=True, raises=()):
        self._git_repos = set(git_repos)
        self.calls = []
        self._sync_result = sync_result
        self._base = base
        self._registered = set(registered)
        self._branches = set(branches)
        self._clone_result = clone_result
        self._sync_default_result = sync_default_result
        self._raises = set(raises)

    def is_git_repo(self, path):
        self.calls.append(("is_git_repo", path))
        return path in self._git_repos

    def sync_to_origin(self, root):
        self.calls.append(("sync_to_origin", root))
        return self._sync_result

    def clone(self, url, dest):
        self.calls.append(("clone", url, dest))
        return self._clone_result

    def sync_to_default_branch(self, root):
        self.calls.append(("sync_to_default_branch", root))
        return self._sync_default_result

    def worktree_base(self, root):
        self.calls.append(("worktree_base", root))
        return self._base

    def branch_exists(self, root, branch):
        self.calls.append(("branch_exists", root, branch))
        if "branch_exists" in self._raises:
            raise GitReadError("git rev-parse failed in %s: fatal: not a git repository" % root)
        return (root, branch) in self._branches

    def worktree_registered(self, root, path):
        self.calls.append(("worktree_registered", root, path))
        if "worktree_registered" in self._raises:
            raise GitReadError(
                "git worktree list failed in %s: fatal: not a git repository" % root
            )
        return path in self._registered

    def git(self, root, *args):
        self.calls.append(("git", root) + args)
        return _GitResult()

    def common_dir(self, root):
        self.calls.append(("common_dir", root))
        if "common_dir" in self._raises:
            raise GitReadError(
                "git rev-parse --git-common-dir failed in %s: fatal: not a git repository" % root
            )
        return os.path.join(root, ".git")

    def remove_worktree(self, root, path):
        self.calls.append(("remove_worktree", root, path))

    def delete_branch(self, root, branch):
        self.calls.append(("delete_branch", root, branch))

    def delete_remote_branch(self, root, branch):
        self.calls.append(("delete_remote_branch", root, branch))


class TestWorktreePath(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        self.svc = WorktreeService(
            self.store, git=None, fs=None, config=_Cfg("/home/u/workspace/projects")
        )

    def test_resolves_under_the_items_target_repo_not_data_root(self):
        item = self.store.create_item("story", "a description")
        self.store.add_project(
            "acme/saga", local_path=os.path.join("/home/u/workspace/projects", "saga")
        )
        self.store.add_artifact(item, "repo", "saga")

        path = self.svc.worktree_path(item)

        self.assertEqual(
            path, os.path.join("/home/u/workspace/projects", "saga", ".worktrees", item)
        )

    def test_absolute_repo_artifact_resolves_directly_not_under_projects_root(self):
        item = self.store.create_item("story", "a description")
        self.store.add_artifact(item, "repo", "/elsewhere/app")

        path = self.svc.worktree_path(item)

        self.assertEqual(path, os.path.join("/elsewhere/app", ".worktrees", item))

    def test_two_items_with_different_repos_resolve_under_their_own_repos(self):
        saga_item = self.store.create_item("saga story", "a description")
        self.store.add_project(
            "acme/saga", local_path=os.path.join("/home/u/workspace/projects", "saga")
        )
        self.store.add_artifact(saga_item, "repo", "saga")
        horde_item = self.store.create_item("horde story", "a description")
        self.store.add_project(
            "acme/horde", local_path=os.path.join("/home/u/workspace/projects", "horde")
        )
        self.store.add_artifact(horde_item, "repo", "horde")

        saga_path = self.svc.worktree_path(saga_item)
        horde_path = self.svc.worktree_path(horde_item)

        self.assertEqual(
            os.path.dirname(os.path.dirname(saga_path)),
            os.path.join("/home/u/workspace/projects", "saga"),
        )
        self.assertEqual(
            os.path.dirname(os.path.dirname(horde_path)),
            os.path.join("/home/u/workspace/projects", "horde"),
        )

    def test_two_phases_in_the_same_repo_get_distinct_worktrees_and_branches(self):
        item = self.store.create_item("Login feature", "a description")
        self.store.add_project(
            "acme/app", local_path=os.path.join("/home/u/workspace/projects", "app")
        )
        self.store.add_artifact(item, "repo", "app")
        cfg = _Cfg("/home/u/workspace/projects")

        def svc(phase):
            return WorktreeService(self.store, git=None, fs=None, config=cfg,
                                   flow=_PhaseFlow(phase))

        feat_path, code_path = svc("feature").worktree_path(item), svc("code").worktree_path(item)
        self.assertEqual(os.path.basename(feat_path), "%s-feature" % item)
        self.assertEqual(os.path.basename(code_path), "%s-code" % item)
        self.assertNotEqual(feat_path, code_path)

        feat_branch, code_branch = svc("feature")._branch_for(item), svc("code")._branch_for(item)
        self.assertEqual(feat_branch, "feat/%s-feature-login-feature" % item)
        self.assertEqual(code_branch, "feat/%s-code-login-feature" % item)
        self.assertNotEqual(feat_branch, code_branch)


class TestItemRepoNoFallback(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        self.svc = WorktreeService(
            self.store, git=None, fs=None, config=_Cfg("/home/u/workspace/projects")
        )

    def test_item_repo_returns_explicit_artifact(self):
        item = self.store.create_item("story", "a description")
        self.store.add_artifact(item, "repo", "saga")

        self.assertEqual(self.svc.item_repo(item), "saga")

    def test_item_repo_raises_when_no_repo_artifact(self):
        item = self.store.create_item("story", "a description")

        with self.assertRaises(UseCaseError):
            self.svc.item_repo(item)

    def test_has_repo_reflects_artifact_presence(self):
        item = self.store.create_item("story", "a description")

        self.assertFalse(self.svc.has_repo(item))
        self.store.add_artifact(item, "repo", "saga")
        self.assertTrue(self.svc.has_repo(item))


class TestSpecsWorkspace(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()

    def test_target_repo_is_specs_root_when_workflow_sources_from_specs(self):
        item = self.store.create_item("spec item", "a description")
        svc = WorktreeService(
            self.store, git=None, fs=None,
            config=_Cfg("/home/u/workspace/projects"), flow=_FakeFlow(workspace="specs"),
        )

        self.assertEqual(svc.target_repo(item), "/specs")

    def test_target_repo_is_projects_root_repo_when_workflow_omits_workspace(self):
        item = self.store.create_item("story", "a description")
        self.store.add_project(
            "acme/saga", local_path=os.path.join("/home/u/workspace/projects", "saga")
        )
        self.store.add_artifact(item, "repo", "saga")
        svc = WorktreeService(
            self.store, git=None, fs=None,
            config=_Cfg("/home/u/workspace/projects"), flow=_FakeFlow(workspace="project"),
        )

        self.assertEqual(
            svc.target_repo(item), os.path.join("/home/u/workspace/projects", "saga")
        )

    def test_target_repo_without_a_flow_falls_back_to_project(self):
        item = self.store.create_item("story", "a description")
        self.store.add_project(
            "acme/saga", local_path=os.path.join("/home/u/workspace/projects", "saga")
        )
        self.store.add_artifact(item, "repo", "saga")
        svc = WorktreeService(
            self.store, git=None, fs=None, config=_Cfg("/home/u/workspace/projects")
        )

        self.assertEqual(
            svc.target_repo(item), os.path.join("/home/u/workspace/projects", "saga")
        )

    def test_ensure_does_not_silently_skip_specs_workspace_without_a_repo_artifact(self):
        item = self.store.create_item("spec item", "a description")
        git = _FakeGit()
        svc = WorktreeService(
            self.store, git, fs=None, config=_Cfg("/home/u/workspace/projects"),
            flow=_FakeFlow(workspace="specs"),
        )

        with self.assertRaises(UseCaseError):
            svc.ensure(item)
        self.assertIn(("is_git_repo", "/specs"), git.calls)

    def test_remove_targets_specs_root_without_a_repo_artifact(self):
        item = self.store.create_item("spec item", "a description")
        self.store.add_artifact(item, "branch", "spec/x")
        git = _FakeGit()
        svc = WorktreeService(
            self.store, git, fs=None, config=_Cfg("/home/u/workspace/projects"),
            flow=_FakeFlow(workspace="specs"),
        )

        svc.remove(item)

        self.assertEqual(git.calls, [("is_git_repo", "/specs")])


class _RaisingFlow:
    def workspace_for_node(self, node):
        raise ValueError("workflow 'lightcycle/spec-driven' is not a pin '<origin>/<name>@<sha>'")

    def phase_for(self, node):
        raise ValueError("workflow 'lightcycle/spec-driven' is not a pin '<origin>/<name>@<sha>'")

    def workspace_for_phase(self, node, phase):
        raise ValueError("workflow 'lightcycle/spec-driven' is not a pin '<origin>/<name>@<sha>'")


class _CloseFlow:
    def workflow_for(self, node):
        return "spec-driven"

    def load_graph(self, name=None):
        return _Graph("project")

    def workspace_for_node(self, node):
        return "project"

    def phase_for(self, node):
        return None

    def workspace_for_phase(self, node, phase):
        return "specs" if phase == "spec" else "project"


class TestRemovePhaseScoped(unittest.TestCase):
    def _item(self):
        store = FakeStore()
        item = store.create_item("Login", "a description")
        store.add_project("acme/app", local_path=os.path.join("/projects", "app"))
        store.add_artifact(item, "repo", "app")
        return store, item

    def test_remove_tears_down_every_recorded_phase_in_its_own_repo(self):
        store, item = self._item()
        store.add_artifact(item, "branch", "spec/login", label="spec")
        store.add_artifact(item, "branch", "feat/app-code-login", label="code")
        target = os.path.join("/projects", "app")
        git = _FakeGit(git_repos={"/specs", target})
        svc = WorktreeService(store, git, fs=None, config=_Cfg("/projects"), flow=_CloseFlow())

        svc.remove(item)

        self.assertIn(
            ("remove_worktree", target, os.path.join(target, ".worktrees", "%s-code" % item)),
            git.calls,
        )
        self.assertIn(("delete_branch", target, "feat/app-code-login"), git.calls)
        self.assertIn(("delete_remote_branch", target, "feat/app-code-login"), git.calls)
        self.assertIn(
            ("remove_worktree", "/specs", os.path.join("/specs", ".worktrees", "%s-spec" % item)),
            git.calls,
        )
        self.assertIn(("delete_branch", "/specs", "spec/login"), git.calls)
        self.assertNotIn(
            ("remove_worktree", target, os.path.join(target, ".worktrees", item)), git.calls
        )

    def test_remove_unlabeled_phase_uses_the_item_worktree_and_branch(self):
        store, item = self._item()
        store.add_artifact(item, "branch", "feat/app-login")
        target = os.path.join("/projects", "app")
        git = _FakeGit(git_repos={target})
        svc = WorktreeService(store, git, fs=None, config=_Cfg("/projects"), flow=_CloseFlow())

        svc.remove(item)

        self.assertIn(
            ("remove_worktree", target, os.path.join(target, ".worktrees", item)), git.calls
        )
        self.assertIn(("delete_branch", target, "feat/app-login"), git.calls)
        self.assertIn(("delete_remote_branch", target, "feat/app-login"), git.calls)


class TestHasWorktreeHistory(unittest.TestCase):
    def test_false_until_ensure_creates_a_branch_artifact(self):
        store = FakeStore()
        item = store.create_item("story", "a description")
        svc = WorktreeService(store, git=None, fs=None, config=_Cfg("/projects"))

        self.assertFalse(svc.has_worktree_history(item))

        store.add_artifact(item, "branch", "feat/x")

        self.assertTrue(svc.has_worktree_history(item))


class TestRemoveNeverActivatedItem(unittest.TestCase):
    def test_remove_is_a_noop_for_a_never_activated_item_under_a_raising_flow(self):
        store = FakeStore()
        item = store.create_item("story", "a description")
        store.add_artifact(item, "repo", "saga")
        git = _FakeGit()
        svc = WorktreeService(
            store, git, fs=None, config=_Cfg("/projects"), flow=_RaisingFlow()
        )

        svc.remove(item)

        self.assertEqual(git.calls, [])

    def test_remove_still_tears_down_when_worktree_history_exists(self):
        store = FakeStore()
        item = store.create_item("story", "a description")
        store.add_project("acme/saga", local_path=os.path.join("/projects", "saga"))
        store.add_artifact(item, "repo", "saga")
        store.add_artifact(item, "branch", "feat/my-branch")
        git = _FakeGit()
        svc = WorktreeService(
            store, git, fs=None, config=_Cfg("/projects"), flow=_FakeFlow(workspace="project")
        )

        svc.remove(item)

        self.assertEqual(git.calls, [("is_git_repo", "/projects/saga")])


class TestPhaseLabelledBranch(unittest.TestCase):
    def test_item_branch_ignores_a_branch_labelled_for_a_different_phase(self):
        store = FakeStore()
        item = store.create_item("spec item", "a description")
        store.add_artifact(item, "branch", "spec/x", label="spec")
        svc = WorktreeService(
            store, git=None, fs=None, config=_Cfg("/projects"), flow=_FakeFlow(workspace="project")
        )

        self.assertIsNone(svc.item_branch(item))

    def test_item_branch_matches_the_current_phase_label(self):
        store = FakeStore()
        item = store.create_item("spec item", "a description")
        store.add_artifact(item, "branch", "spec/x", label="spec")
        store.add_artifact(item, "branch", "feat/x", label="code")
        svc = WorktreeService(
            store, git=None, fs=None, config=_Cfg("/projects"), flow=_FakeFlow(workspace="project")
        )

        self.assertEqual(svc.item_branch(item), "feat/x")

    def test_ensure_branch_artifact_labels_the_new_branch_with_the_current_phase(self):
        store = FakeStore()
        item = store.create_item("code item", "a description")
        store.add_artifact(item, "branch", "spec/x", label="spec")
        svc = WorktreeService(
            store, git=None, fs=None, config=_Cfg("/projects"), flow=_FakeFlow(workspace="project")
        )

        svc._ensure_branch_artifact(item, "feat/y")

        branches = {a.label: a.value for a in store.item_artifacts(item) if a.type == "branch"}
        self.assertEqual(branches, {"spec": "spec/x", "code": "feat/y"})


class TestEnsureNoSilentFailure(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()

    def test_ensure_returns_none_when_item_has_no_repo(self):
        item = self.store.create_item("story", "a description")
        git = _FakeGit()
        svc = WorktreeService(self.store, git, fs=None, config=_Cfg("/projects"))

        self.assertIsNone(svc.ensure(item))
        self.assertEqual(git.calls, [])

    def test_ensure_raises_when_repo_present_but_not_a_git_repo(self):
        item = self.store.create_item("story", "a description")
        self.store.add_project("acme/saga", local_path=os.path.join("/projects", "saga"))
        self.store.add_artifact(item, "repo", "saga")
        git = _FakeGit(git_repos=())
        svc = WorktreeService(self.store, git, fs=None, config=_Cfg("/projects"))

        with self.assertRaises(UseCaseError):
            svc.ensure(item)


class TestEnsureSyncsOrigin(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        self.projects_root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.projects_root, True)

    def _item_with_repo(self, repo="saga"):
        item = self.store.create_item("story", "a description")
        self.store.add_project(
            "acme/%s" % repo, local_path=os.path.join(self.projects_root, repo)
        )
        self.store.add_artifact(item, "repo", repo)
        return item

    def test_new_branch_path_syncs_origin_before_resolving_the_worktree_base(self):
        item = self._item_with_repo()
        target = os.path.join(self.projects_root, "saga")
        git = _FakeGit(git_repos={target}, sync_result=True, base="origin/main")
        svc = WorktreeService(self.store, git, FakeFs(), _Cfg(self.projects_root))

        svc.ensure(item)

        kinds = [c[0] for c in git.calls]
        self.assertIn("sync_to_origin", kinds)
        self.assertLess(kinds.index("sync_to_origin"), kinds.index("worktree_base"))

    def test_already_registered_worktree_does_not_sync(self):
        item = self._item_with_repo()
        target = os.path.join(self.projects_root, "saga")
        path = os.path.join(target, ".worktrees", item)
        os.makedirs(path, exist_ok=True)
        git = _FakeGit(git_repos={target}, registered={path})
        svc = WorktreeService(self.store, git, FakeFs(), _Cfg(self.projects_root))

        result = svc.ensure(item)

        self.assertEqual(result, path)
        self.assertNotIn("sync_to_origin", [c[0] for c in git.calls])

    def test_ensure_raises_and_never_resolves_base_or_adds_a_worktree_when_sync_fails(self):
        item = self._item_with_repo()
        target = os.path.join(self.projects_root, "saga")
        git = _FakeGit(git_repos={target}, sync_result=False)
        svc = WorktreeService(self.store, git, FakeFs(), _Cfg(self.projects_root))

        with self.assertRaises(UseCaseError):
            svc.ensure(item)

        kinds = [c[0] for c in git.calls]
        self.assertNotIn("worktree_base", kinds)
        self.assertNotIn("git", kinds)

    def test_sync_is_keyed_on_the_resolved_target_not_a_hardcoded_workspace_name(self):
        item = self._item_with_repo()
        self.store.add_project(
            "acme/staging", local_path=os.path.join(self.projects_root, "staging")
        )
        target = os.path.join(self.projects_root, "staging")
        git = _FakeGit(git_repos={target}, sync_result=True, base="origin/main")
        svc = WorktreeService(
            self.store, git, FakeFs(), _Cfg(self.projects_root), flow=_FakeFlow(workspace="staging")
        )

        svc.ensure(item)

        self.assertIn(("sync_to_origin", target), git.calls)

    def test_ensure_proceeds_to_add_a_worktree_when_worktree_registered_is_unreadable(self):
        item = self._item_with_repo()
        target = os.path.join(self.projects_root, "saga")
        git = _FakeGit(
            git_repos={target}, sync_result=True, base="origin/main",
            branches={(target, self.store.get_node(item).id)}, raises={"worktree_registered"},
        )
        svc = WorktreeService(self.store, git, FakeFs(), _Cfg(self.projects_root))

        svc.ensure(item)

        kinds = [c[0] for c in git.calls]
        self.assertIn("worktree_registered", kinds)
        self.assertIn("git", kinds)

    def test_ensure_treats_an_unreadable_branch_exists_as_a_new_branch(self):
        item = self._item_with_repo()
        target = os.path.join(self.projects_root, "saga")
        git = _FakeGit(
            git_repos={target}, sync_result=True, base="origin/main", raises={"branch_exists"},
        )
        svc = WorktreeService(self.store, git, FakeFs(), _Cfg(self.projects_root))

        svc.ensure(item)

        kinds = [c[0] for c in git.calls]
        self.assertIn("sync_to_origin", kinds)
        self.assertIn("worktree_base", kinds)

    def test_ensure_raises_when_common_dir_is_unreadable(self):
        item = self._item_with_repo()
        target = os.path.join(self.projects_root, "saga")
        git = _FakeGit(
            git_repos={target}, sync_result=True, base="origin/main", raises={"common_dir"},
        )
        svc = WorktreeService(self.store, git, FakeFs(), _Cfg(self.projects_root))

        with self.assertRaises(UseCaseError):
            svc.ensure(item)


class TestSyncSpecs(unittest.TestCase):
    def test_clones_when_specs_root_is_not_a_git_repo(self):
        git = _FakeGit(git_repos=(), clone_result=True, sync_default_result=True)
        svc = WorktreeService(FakeStore(), git=git, fs=None,
                              config=_Cfg("/proj", specs_root="/specs",
                                          specs_remote="git@x:specs.git"))

        svc.sync_specs()

        self.assertIn(("clone", "git@x:specs.git", "/specs"), git.calls)

    def test_does_not_clone_when_specs_root_is_already_a_git_repo(self):
        git = _FakeGit(git_repos={"/specs"}, sync_default_result=True)
        svc = WorktreeService(FakeStore(), git=git, fs=None,
                              config=_Cfg("/proj", specs_root="/specs",
                                          specs_remote="git@x:specs.git"))

        svc.sync_specs()

        self.assertNotIn(("clone", "git@x:specs.git", "/specs"), git.calls)

    def test_raises_when_clone_fails(self):
        git = _FakeGit(git_repos=(), clone_result=False)
        svc = WorktreeService(FakeStore(), git=git, fs=None,
                              config=_Cfg("/proj", specs_root="/specs",
                                          specs_remote="git@x:specs.git"))

        with self.assertRaises(UseCaseError):
            svc.sync_specs()

    def test_raises_when_sync_to_default_branch_fails(self):
        git = _FakeGit(git_repos={"/specs"}, sync_default_result=False)
        svc = WorktreeService(FakeStore(), git=git, fs=None,
                              config=_Cfg("/proj", specs_root="/specs",
                                          specs_remote="git@x:specs.git"))

        with self.assertRaises(UseCaseError):
            svc.sync_specs()


if __name__ == "__main__":
    unittest.main()


class _LoopFlow:
    def __init__(self, phase_by_step):
        self._phase_by_step = phase_by_step

    def workflow_for(self, node):
        return "loop"

    def load_graph(self, name=None):
        return _Graph("project")

    def workspace_for_node(self, node):
        return "project"

    def phase_for(self, node):
        return self._phase_by_step.get(getattr(node, "step", None))

    def workspace_for_phase(self, node, phase):
        return "project"


class TestPhaseReEntry(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        self.phases = {"spec-writer": "spec", "build": "code"}
        self.flow = _LoopFlow(self.phases)
        self.git = _FakeGit(git_repos={os.path.join("/home/u/workspace/projects", "saga")})
        self.svc = WorktreeService(
            self.store, git=self.git, fs=None,
            config=_Cfg("/home/u/workspace/projects"), flow=self.flow,
        )
        self.item = self.store.create_item("deliver the blueprint", "a description")
        self.store.add_project(
            "acme/saga", local_path=os.path.join("/home/u/workspace/projects", "saga")
        )
        self.store.add_artifact(self.item, "repo", "saga")

    def _step(self, step):
        return self.store.create_step("%s: work" % step, step=step, parent=self.item)

    def _close(self, sid):
        self.store.update_state(sid, "done")

    def test_a_second_pass_through_a_phase_mints_a_new_branch(self):
        first = self._step("spec-writer")
        self.svc._ensure_branch_artifact(self.item, self.svc._branch_for(self.item))
        first_branch = self.svc.item_branch(self.item)
        self._close(first)
        self._close(self._step("build"))

        self._step("spec-writer")
        self.svc._ensure_branch_artifact(self.item, self.svc._branch_for(self.item))

        self.assertNotEqual(self.svc.item_branch(self.item), first_branch)
        self.assertIn("spec-2", self.svc.item_branch(self.item))

    def test_a_second_pass_leaves_the_previous_runs_remote_branch_alone(self):
        first = self._step("spec-writer")
        self.svc._ensure_branch_artifact(self.item, self.svc._branch_for(self.item))
        first_branch = self.svc.item_branch(self.item)
        self._close(first)
        self._close(self._step("build"))

        self._step("spec-writer")
        self.svc._ensure_branch_artifact(self.item, self.svc._branch_for(self.item))

        deleted = [c for c in self.git.calls if c[0] == "delete_remote_branch"]
        self.assertEqual(deleted, [])
        target = os.path.join("/home/u/workspace/projects", "saga")
        self.assertIn(("delete_branch", target, first_branch), self.git.calls)

    def test_steps_within_one_pass_share_the_phases_branch(self):
        self._step("spec-writer")
        self.svc._ensure_branch_artifact(self.item, self.svc._branch_for(self.item))
        branch = self.svc.item_branch(self.item)

        self._step("spec-writer")
        self.svc._ensure_branch_artifact(self.item, self.svc._branch_for(self.item))

        self.assertEqual(self.svc.item_branch(self.item), branch)

    def test_the_phases_branch_artifact_is_replaced_not_accumulated(self):
        self._step("spec-writer")
        self.svc._ensure_branch_artifact(self.item, self.svc._branch_for(self.item))
        self._close(self._step("build"))
        self._step("spec-writer")
        self.svc._ensure_branch_artifact(self.item, self.svc._branch_for(self.item))

        branches = [
            a for a in self.store.item_artifacts(self.item) if a.type == "branch"
        ]
        self.assertEqual(len(branches), 1)

    def test_a_second_pass_gets_its_own_worktree_path(self):
        self._step("spec-writer")
        first_path = self.svc.worktree_path(self.item)
        self._close(self._step("build"))
        self._step("spec-writer")

        self.assertNotEqual(self.svc.worktree_path(self.item), first_path)

    def test_a_single_pass_workflow_is_unchanged(self):
        self._step("spec-writer")
        self.svc._ensure_branch_artifact(self.item, self.svc._branch_for(self.item))

        self.assertNotIn("spec-2", self.svc.item_branch(self.item))
        self.assertTrue(self.svc.worktree_path(self.item).endswith("%s-spec" % self.item))


    def test_a_superseded_run_has_its_worktree_and_branch_released(self):
        self._step("spec-writer")
        self.svc._ensure_branch_artifact(self.item, self.svc._branch_for(self.item))
        spent = self.svc.item_branch(self.item)
        self._close(self._step("build"))

        self._step("spec-writer")
        self.svc._ensure_branch_artifact(self.item, self.svc._branch_for(self.item))

        saga = os.path.join("/home/u/workspace/projects", "saga")
        self.assertIn(
            ("remove_worktree", saga, os.path.join(saga, ".worktrees", "%s-spec" % self.item)),
            self.git.calls,
        )
        self.assertIn(("delete_branch", saga, spent), self.git.calls)

    def test_a_first_run_releases_nothing(self):
        self._step("spec-writer")
        self.svc._ensure_branch_artifact(self.item, self.svc._branch_for(self.item))

        self.assertFalse([c for c in self.git.calls if c[0] == "remove_worktree"])


class _ExplodingGitHub:
    def is_merged(self, pr):
        raise AssertionError("must not query github when no pr artifact is recorded")

    def is_closed_unmerged(self, pr):
        raise AssertionError("must not query github when no pr artifact is recorded")


class TestPhaseReEntryWithOpenPr(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        self.phases = {"spec-writer": "spec", "build": "code"}
        self.flow = _LoopFlow(self.phases)
        self.git = _FakeGit(git_repos={os.path.join("/home/u/workspace/projects", "saga")})
        self.item = self.store.create_item("deliver the blueprint", "a description")
        self.store.add_project(
            "acme/saga", local_path=os.path.join("/home/u/workspace/projects", "saga")
        )
        self.store.add_artifact(self.item, "repo", "saga")

    def _svc(self, github):
        return WorktreeService(
            self.store, git=self.git, fs=None,
            config=_Cfg("/home/u/workspace/projects"), flow=self.flow, github=github,
        )

    def _step(self, step):
        return self.store.create_step("%s: work" % step, step=step, parent=self.item)

    def _close(self, sid):
        self.store.update_state(sid, "done")

    def test_a_still_open_pr_keeps_the_same_branch_and_worktree(self):
        svc = self._svc(FakeGitHub())
        first = self._step("spec-writer")
        svc._ensure_branch_artifact(self.item, svc._branch_for(self.item))
        first_branch = svc.item_branch(self.item)
        first_path = svc.worktree_path(self.item)
        self.store.add_artifact(
            self.item, "pr", "https://github.com/x/y/pull/369", label="spec"
        )
        self._close(first)
        self._close(self._step("build"))

        self._step("spec-writer")
        svc._ensure_branch_artifact(self.item, svc._branch_for(self.item))

        self.assertEqual(svc.item_branch(self.item), first_branch)
        self.assertEqual(svc.worktree_path(self.item), first_path)
        self.assertFalse([
            c for c in self.git.calls
            if c[0] in ("delete_branch", "delete_remote_branch", "remove_worktree")
        ])

    def test_a_still_open_pr_keeps_the_same_branch_across_repeated_boundary_crossings(self):
        svc = self._svc(FakeGitHub())
        first = self._step("spec-writer")
        svc._ensure_branch_artifact(self.item, svc._branch_for(self.item))
        first_branch = svc.item_branch(self.item)
        self.store.add_artifact(
            self.item, "pr", "https://github.com/x/y/pull/369", label="spec"
        )
        self._close(first)
        self._close(self._step("build"))
        self._close(self._step("spec-writer"))
        self._close(self._step("build"))

        self._step("spec-writer")
        svc._ensure_branch_artifact(self.item, svc._branch_for(self.item))

        self.assertEqual(svc.item_branch(self.item), first_branch)
        self.assertFalse([
            c for c in self.git.calls
            if c[0] in ("delete_branch", "delete_remote_branch", "remove_worktree")
        ])

    def test_a_merged_pr_still_mints_a_new_branch(self):
        pr_url = "https://github.com/x/y/pull/370"
        svc = self._svc(FakeGitHub(merged_prs={pr_url}))
        first = self._step("spec-writer")
        svc._ensure_branch_artifact(self.item, svc._branch_for(self.item))
        first_branch = svc.item_branch(self.item)
        self.store.add_artifact(self.item, "pr", pr_url, label="spec")
        self._close(first)
        self._close(self._step("build"))

        self._step("spec-writer")
        svc._ensure_branch_artifact(self.item, svc._branch_for(self.item))

        self.assertNotEqual(svc.item_branch(self.item), first_branch)
        self.assertIn("spec-2", svc.item_branch(self.item))

    def test_a_closed_unmerged_pr_still_mints_a_new_branch(self):
        pr_url = "https://github.com/x/y/pull/371"
        svc = self._svc(FakeGitHub(closed_prs={pr_url}))
        first = self._step("spec-writer")
        svc._ensure_branch_artifact(self.item, svc._branch_for(self.item))
        first_branch = svc.item_branch(self.item)
        self.store.add_artifact(self.item, "pr", pr_url, label="spec")
        self._close(first)
        self._close(self._step("build"))

        self._step("spec-writer")
        svc._ensure_branch_artifact(self.item, svc._branch_for(self.item))

        self.assertNotEqual(svc.item_branch(self.item), first_branch)
        self.assertIn("spec-2", svc.item_branch(self.item))

    def test_no_pr_artifact_mints_a_new_branch_without_querying_github(self):
        svc = self._svc(_ExplodingGitHub())
        first = self._step("spec-writer")
        svc._ensure_branch_artifact(self.item, svc._branch_for(self.item))
        first_branch = svc.item_branch(self.item)
        self._close(first)
        self._close(self._step("build"))

        self._step("spec-writer")
        svc._ensure_branch_artifact(self.item, svc._branch_for(self.item))

        self.assertNotEqual(svc.item_branch(self.item), first_branch)
        self.assertIn("spec-2", svc.item_branch(self.item))


class TestNamedWorkspace(unittest.TestCase):
    def setUp(self):
        self.projects_root = "/home/u/workspace/projects"
        self.store = FakeStore()
        self.item = self.store.create_item("story", "a description")
        self.store.add_project(
            "acme/saga", local_path=os.path.join(self.projects_root, "saga")
        )
        self.store.add_project(
            "acme/blueprints", local_path=os.path.join(self.projects_root, "blueprints")
        )
        self.store.add_artifact(self.item, "repo", "saga")

    def _svc(self, workspace):
        return WorktreeService(
            self.store, git=None, fs=None, config=_Cfg(self.projects_root),
            flow=_FakeFlow(workspace=workspace),
        )

    def test_a_named_workspace_resolves_to_that_registered_project(self):
        target = self._svc("blueprints").target_repo(self.item)

        self.assertEqual(target, os.path.join(self.projects_root, "blueprints"))

    def test_the_default_workspace_still_uses_the_items_own_repo(self):
        target = self._svc("project").target_repo(self.item)

        self.assertEqual(target, os.path.join(self.projects_root, "saga"))

    def test_specs_remains_an_alias_for_the_configured_specs_root(self):
        target = self._svc("specs").target_repo(self.item)

        self.assertEqual(target, "/specs")

    def test_an_unregistered_workspace_name_fails_rather_than_silently_using_the_item_repo(self):
        with self.assertRaises(UseCaseError):
            self._svc("not-a-project").target_repo(self.item)

    def test_a_named_workspace_needs_no_repo_artifact_on_the_item(self):
        bare = self.store.create_item("no repo", "a description")

        target = self._svc("blueprints").target_repo(bare)

        self.assertEqual(target, os.path.join(self.projects_root, "blueprints"))
