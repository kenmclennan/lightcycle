import os
import shutil
import tempfile
import unittest

from lightcycle.adapters.scaffold import ScaffoldAdapter
from lightcycle.application.errors import UseCaseError
from lightcycle.application.services.worktree import WorktreeService
from lightcycle.application.flow.passes import PassBook
from lightcycle.domain.flow.flow import SPECS_WORKSPACE
from lightcycle.domain.work import State
from tests.support.fake_fs import FakeFs
from tests.support.fake_git import FakeGit
from tests.support.fake_store import FakeStore


class _Cfg:
    def __init__(self, projects_root, engine_root="lightcycle"):
        self._projects_root = projects_root
        self._engine_root = engine_root

    def projects_root(self):
        return self._projects_root

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


def plant_run(store, item, phase, branch=None, n=1, state="open"):
    while store.current_pass(item) is None or store.current_pass(item).n < n:
        current = store.current_pass(item)
        if current is not None:
            store.close_pass(current.id)
        store.open_pass(item)
    rid = store.open_run(item, store.current_pass(item).id, phase)
    if branch is not None:
        store.set_branch(rid, branch)
    if state != "open":
        store.close_run(rid, state)
    return rid


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

        path = self.svc.worktree_path(self.store.get_node(item))

        self.assertEqual(
            path, os.path.join("/home/u/workspace/projects", "saga", ".worktrees", item)
        )

    def test_absolute_repo_artifact_resolves_directly_not_under_projects_root(self):
        item = self.store.create_item("story", "a description")
        self.store.add_artifact(item, "repo", "/elsewhere/app")

        path = self.svc.worktree_path(self.store.get_node(item))

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

        saga_path = self.svc.worktree_path(self.store.get_node(saga_item))
        horde_path = self.svc.worktree_path(self.store.get_node(horde_item))

        self.assertEqual(
            os.path.dirname(os.path.dirname(saga_path)),
            os.path.join("/home/u/workspace/projects", "saga"),
        )
        self.assertEqual(
            os.path.dirname(os.path.dirname(horde_path)),
            os.path.join("/home/u/workspace/projects", "horde"),
        )

    def test_path_for_run_matches_worktree_path_for_the_runs_own_phase(self):
        item = self.store.create_item("Login feature", "a description")
        self.store.add_project(
            "acme/app", local_path=os.path.join("/home/u/workspace/projects", "app")
        )
        self.store.add_artifact(item, "repo", "app")
        svc = WorktreeService(
            self.store, git=None, fs=None,
            config=_Cfg("/home/u/workspace/projects"), flow=_PhaseFlow("code"),
        )
        rid = plant_run(self.store, item, "code", branch="feat/app-code-login")
        run = self.store.get_run(rid)

        path = svc.path_for_run(run)

        self.assertEqual(
            path, os.path.join("/home/u/workspace/projects", "app", ".worktrees", "%s-code" % item)
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

        feat_path, code_path = svc("feature").worktree_path(self.store.get_node(item)), svc("code").worktree_path(self.store.get_node(item))
        self.assertEqual(os.path.basename(feat_path), "%s-feature" % item)
        self.assertEqual(os.path.basename(code_path), "%s-code" % item)
        self.assertNotEqual(feat_path, code_path)

        feat_branch, code_branch = svc("feature")._branch_for(self.store.get_node(item)), svc("code")._branch_for(self.store.get_node(item))
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
        self.store.add_project(SPECS_WORKSPACE, local_path="/specs")

    def test_target_repo_is_specs_root_when_workflow_sources_from_specs(self):
        item = self.store.create_item("spec item", "a description")
        svc = WorktreeService(
            self.store, git=None, fs=None,
            config=_Cfg("/home/u/workspace/projects"), flow=_FakeFlow(workspace="specs"),
        )

        self.assertEqual(svc.target_repo(self.store.get_node(item)), "/specs")

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
            svc.target_repo(self.store.get_node(item)), os.path.join("/home/u/workspace/projects", "saga")
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
            svc.target_repo(self.store.get_node(item)), os.path.join("/home/u/workspace/projects", "saga")
        )

    def test_ensure_does_not_silently_skip_specs_workspace_without_a_repo_artifact(self):
        item = self.store.create_item("spec item", "a description")
        git = FakeGit(repos=())
        svc = WorktreeService(
            self.store, git, fs=None, config=_Cfg("/home/u/workspace/projects"),
            flow=_FakeFlow(workspace="specs"),
        )

        with self.assertRaises(UseCaseError):
            svc.ensure(self.store.get_node(item))
        self.assertIn(("is_git_repo", "/specs"), git.calls)

    def test_remove_targets_specs_root_without_a_repo_artifact(self):
        item = self.store.create_item("spec item", "a description")
        plant_run(self.store, item, "spec", "spec/x")
        git = FakeGit(repos=())
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
        store.add_project(SPECS_WORKSPACE, local_path="/specs")
        item = store.create_item("Login", "a description")
        store.add_project("acme/app", local_path=os.path.join("/projects", "app"))
        store.add_artifact(item, "repo", "app")
        return store, item

    def test_remove_tears_down_every_recorded_phase_in_its_own_repo(self):
        store, item = self._item()
        plant_run(store, item, "spec", "spec/login")
        plant_run(store, item, "code", "feat/app-code-login")
        target = os.path.join("/projects", "app")
        git = FakeGit(repos={"/specs", target})
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
        plant_run(store, item, None, "feat/app-login")
        target = os.path.join("/projects", "app")
        git = FakeGit(repos={target})
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

        plant_run(store, item, None, "feat/x")

        self.assertTrue(svc.has_worktree_history(item))


class TestRemoveNeverActivatedItem(unittest.TestCase):
    def test_remove_is_a_noop_for_a_never_activated_item_under_a_raising_flow(self):
        store = FakeStore()
        item = store.create_item("story", "a description")
        store.add_artifact(item, "repo", "saga")
        git = FakeGit()
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
        plant_run(store, item, None, "feat/my-branch")
        git = FakeGit(repos=())
        svc = WorktreeService(
            store, git, fs=None, config=_Cfg("/projects"), flow=_FakeFlow(workspace="project")
        )

        svc.remove(item)

        self.assertEqual(git.calls, [("is_git_repo", "/projects/saga")])


class TestPhaseLabelledBranch(unittest.TestCase):
    def test_item_branch_ignores_a_branch_labelled_for_a_different_phase(self):
        store = FakeStore()
        item = store.create_item("spec item", "a description")
        plant_run(store, item, "spec", "spec/x")
        svc = WorktreeService(
            store, git=None, fs=None, config=_Cfg("/projects"), flow=_FakeFlow(workspace="project")
        )

        self.assertIsNone(svc.item_branch(store.get_node(item)))

    def test_item_branch_reads_the_run_for_the_current_phase(self):
        store = FakeStore()
        item = store.create_item("spec item", "a description")
        plant_run(store, item, "spec", "spec/x")
        plant_run(store, item, "code", "feat/x")
        svc = WorktreeService(
            store, git=None, fs=None, config=_Cfg("/projects"), flow=_FakeFlow(workspace="project")
        )

        self.assertEqual(svc.item_branch(store.get_node(item)), "feat/x")

    def test_the_branch_lands_on_the_current_phases_run_leaving_the_others_alone(self):
        store = FakeStore()
        item = store.create_item("code item", "a description")
        plant_run(store, item, "spec", "spec/x")
        plant_run(store, item, "code")
        svc = WorktreeService(
            store, git=None, fs=None, config=_Cfg("/projects"), flow=_FakeFlow(workspace="project")
        )

        svc._ensure_branch_artifact(store.get_node(item), "feat/y")

        self.assertEqual({r.phase: r.branch for r in store.runs_of(item)},
                         {"spec": "spec/x", "code": "feat/y"})


class TestEnsureNoSilentFailure(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()

    def test_ensure_returns_none_when_item_has_no_repo(self):
        item = self.store.create_item("story", "a description")
        git = FakeGit()
        svc = WorktreeService(self.store, git, fs=None, config=_Cfg("/projects"))

        self.assertIsNone(svc.ensure(self.store.get_node(item)))
        self.assertEqual(git.calls, [])

    def test_ensure_raises_when_repo_present_but_not_a_git_repo(self):
        item = self.store.create_item("story", "a description")
        self.store.add_project("acme/saga", local_path=os.path.join("/projects", "saga"))
        self.store.add_artifact(item, "repo", "saga")
        git = FakeGit(repos=())
        svc = WorktreeService(self.store, git, fs=None, config=_Cfg("/projects"))

        with self.assertRaises(UseCaseError):
            svc.ensure(self.store.get_node(item))


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
        git = FakeGit(repos={target}, sync_result=True, base="origin/main")
        svc = WorktreeService(self.store, git, FakeFs(), _Cfg(self.projects_root), scaffold=ScaffoldAdapter())

        svc.ensure(self.store.get_node(item))

        kinds = [c[0] for c in git.calls]
        self.assertIn("sync_to_origin", kinds)
        self.assertLess(kinds.index("sync_to_origin"), kinds.index("worktree_base"))

    def test_already_registered_worktree_does_not_sync(self):
        item = self._item_with_repo()
        target = os.path.join(self.projects_root, "saga")
        path = os.path.join(target, ".worktrees", item)
        os.makedirs(path, exist_ok=True)
        git = FakeGit(repos={target}, registered={path})
        svc = WorktreeService(self.store, git, FakeFs(), _Cfg(self.projects_root), scaffold=ScaffoldAdapter())

        result = svc.ensure(self.store.get_node(item))

        self.assertEqual(result, path)
        self.assertNotIn("sync_to_origin", [c[0] for c in git.calls])

    def test_ensure_raises_and_never_resolves_base_or_adds_a_worktree_when_sync_fails(self):
        item = self._item_with_repo()
        target = os.path.join(self.projects_root, "saga")
        git = FakeGit(repos={target}, sync_result=False)
        svc = WorktreeService(self.store, git, FakeFs(), _Cfg(self.projects_root))

        with self.assertRaises(UseCaseError):
            svc.ensure(self.store.get_node(item))

        kinds = [c[0] for c in git.calls]
        self.assertNotIn("worktree_base", kinds)
        self.assertNotIn("add_worktree", kinds)

    def test_sync_is_keyed_on_the_resolved_target_not_a_hardcoded_workspace_name(self):
        item = self._item_with_repo()
        self.store.add_project(
            "acme/staging", local_path=os.path.join(self.projects_root, "staging")
        )
        target = os.path.join(self.projects_root, "staging")
        git = FakeGit(repos={target}, sync_result=True, base="origin/main")
        svc = WorktreeService(
            self.store, git, FakeFs(), _Cfg(self.projects_root), flow=_FakeFlow(workspace="staging"),
            scaffold=ScaffoldAdapter(),
        )

        svc.ensure(self.store.get_node(item))

        self.assertIn(("sync_to_origin", target), git.calls)

    def test_ensure_proceeds_to_add_a_worktree_when_worktree_registered_is_unreadable(self):
        item = self._item_with_repo()
        target = os.path.join(self.projects_root, "saga")
        git = FakeGit(
            repos={target}, sync_result=True, base="origin/main",
            branches={(target, self.store.get_node(item).id)}, raises={"worktree_registered"},
        )
        svc = WorktreeService(self.store, git, FakeFs(), _Cfg(self.projects_root), scaffold=ScaffoldAdapter())

        svc.ensure(self.store.get_node(item))

        kinds = [c[0] for c in git.calls]
        self.assertIn("worktree_registered", kinds)
        self.assertIn("add_worktree", kinds)

    def test_ensure_treats_an_unreadable_branch_exists_as_a_new_branch(self):
        item = self._item_with_repo()
        target = os.path.join(self.projects_root, "saga")
        git = FakeGit(
            repos={target}, sync_result=True, base="origin/main", raises={"branch_exists"},
        )
        svc = WorktreeService(self.store, git, FakeFs(), _Cfg(self.projects_root), scaffold=ScaffoldAdapter())

        svc.ensure(self.store.get_node(item))

        kinds = [c[0] for c in git.calls]
        self.assertIn("sync_to_origin", kinds)
        self.assertIn("worktree_base", kinds)

    def test_ensure_raises_when_common_dir_is_unreadable(self):
        item = self._item_with_repo()
        target = os.path.join(self.projects_root, "saga")
        git = FakeGit(
            repos={target}, sync_result=True, base="origin/main", raises={"common_dir"},
        )
        svc = WorktreeService(self.store, git, FakeFs(), _Cfg(self.projects_root), scaffold=ScaffoldAdapter())

        with self.assertRaises(UseCaseError):
            svc.ensure(self.store.get_node(item))

    def test_branch_is_recorded_even_when_worktree_add_fails(self):
        item = self._item_with_repo()
        target = os.path.join(self.projects_root, "saga")
        git = FakeGit(
            repos={target}, sync_result=True, base="origin/main", worktree_add_fails=True,
        )
        svc = WorktreeService(self.store, git, FakeFs(), _Cfg(self.projects_root), scaffold=ScaffoldAdapter())

        with self.assertRaises(UseCaseError):
            svc.ensure(self.store.get_node(item))

        self.assertTrue(svc.has_worktree_history(item))


class TestSyncSpecs(unittest.TestCase):
    def _store(self):
        store = FakeStore()
        store.add_project(SPECS_WORKSPACE, local_path="/specs", remote="git@x:specs.git")
        return store

    def test_clones_when_specs_root_is_not_a_git_repo(self):
        git = FakeGit(repos=(), clone_result=True, sync_default_result=True)
        svc = WorktreeService(self._store(), git=git, fs=None, config=_Cfg("/proj"))

        svc.sync_specs()

        self.assertIn(("clone", "git@x:specs.git", "/specs"), git.calls)

    def test_does_not_clone_when_specs_root_is_already_a_git_repo(self):
        git = FakeGit(repos={"/specs"}, sync_default_result=True)
        svc = WorktreeService(self._store(), git=git, fs=None, config=_Cfg("/proj"))

        svc.sync_specs()

        self.assertNotIn(("clone", "git@x:specs.git", "/specs"), git.calls)

    def test_raises_when_clone_fails(self):
        git = FakeGit(repos=(), clone_result=False)
        svc = WorktreeService(self._store(), git=git, fs=None, config=_Cfg("/proj"))

        with self.assertRaises(UseCaseError):
            svc.sync_specs()

    def test_raises_when_sync_to_default_branch_fails(self):
        git = FakeGit(repos={"/specs"}, sync_default_result=False)
        svc = WorktreeService(self._store(), git=git, fs=None, config=_Cfg("/proj"))

        with self.assertRaises(UseCaseError):
            svc.sync_specs()

    def test_raises_with_no_specs_project_registered(self):
        git = FakeGit()
        svc = WorktreeService(FakeStore(), git=git, fs=None, config=_Cfg("/proj"))

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
        return self._phase_by_step.get(getattr(node, "stage", None))

    def workspace_for_phase(self, node, phase):
        return "project"


class TestPhaseReEntry(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        self.phases = {"spec-writer": "spec", "build": "code"}
        self.flow = _LoopFlow(self.phases)
        self.git = FakeGit(repos={os.path.join("/home/u/workspace/projects", "saga")})
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
        sid = self.store.create_step(step=step, parent=self.item)
        self.step = self.store.get_node(sid)
        return sid

    def test_a_first_pass_keeps_the_bare_phase_key(self):
        self._step("spec-writer")
        plant_run(self.store, self.item, "spec")

        self.assertEqual(self.svc._phase_key(self.step), "spec")

    def test_a_second_pass_gets_its_own_worktree_path(self):
        self._step("spec-writer")
        plant_run(self.store, self.item, "spec", "spec/one", n=1, state="merged")
        plant_run(self.store, self.item, "spec", n=2)

        self.assertTrue(self.svc.worktree_path(self.step).endswith("-spec-2"))

    def test_a_second_pass_through_a_phase_mints_a_new_branch(self):
        self._step("spec-writer")
        plant_run(self.store, self.item, "spec", "spec/one", n=1, state="merged")
        plant_run(self.store, self.item, "spec", n=2)

        branch = self.svc._branch_for(self.step)

        self.assertNotEqual(branch, "spec/one")
        self.assertIn("spec-2", branch)

    def test_a_still_open_run_keeps_its_branch_rather_than_minting_another(self):
        self._step("spec-writer")
        plant_run(self.store, self.item, "spec", "spec/one")

        self.assertEqual(self.svc._branch_for(self.step), "spec/one")

    def test_the_run_holds_one_branch_and_replaces_it_rather_than_accumulating(self):
        self._step("spec-writer")
        plant_run(self.store, self.item, "spec", "spec/one")

        self.svc._ensure_branch_artifact(self.step, "spec/two")

        self.assertEqual([r.branch for r in self.store.runs_of(self.item)], ["spec/two"])

    def test_closing_a_run_releases_its_worktree_and_branch_with_the_item_still_open(self):
        self._step("spec-writer")
        rid = plant_run(self.store, self.item, "spec", "spec/one")
        run = self.store.get_run(rid)

        self.svc.release_run(run)

        target = os.path.join("/home/u/workspace/projects", "saga")
        self.assertIn(("delete_branch", target, "spec/one"), self.git.calls)
        self.assertIn(("delete_remote_branch", target, "spec/one"), self.git.calls)
        self.assertNotEqual(self.store.get_node(self.item).state, "done")

    def test_releasing_a_run_leaves_another_passs_branch_alone(self):
        self._step("spec-writer")
        first = plant_run(self.store, self.item, "spec", "spec/one", n=1, state="merged")
        plant_run(self.store, self.item, "spec", "spec/two", n=2)

        self.svc.release_run(self.store.get_run(first))

        target = os.path.join("/home/u/workspace/projects", "saga")
        self.assertNotIn(("delete_branch", target, "spec/two"), self.git.calls)

    def test_a_run_with_no_branch_releases_nothing(self):
        self._step("spec-writer")
        rid = plant_run(self.store, self.item, "spec")

        self.svc.release_run(self.store.get_run(rid))

        self.assertEqual(self.git.calls, [])

    def test_the_pass_number_never_asks_github_anything(self):
        self._step("spec-writer")
        plant_run(self.store, self.item, "spec", "spec/one", n=1, state="merged")
        plant_run(self.store, self.item, "spec", n=2)

        self.assertTrue(self.svc.worktree_path(self.step).endswith("-spec-2"))


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
        self.store.add_project(SPECS_WORKSPACE, local_path="/specs")
        self.store.add_artifact(self.item, "repo", "saga")

    def _svc(self, workspace):
        return WorktreeService(
            self.store, git=None, fs=None, config=_Cfg(self.projects_root),
            flow=_FakeFlow(workspace=workspace),
        )

    def test_a_named_workspace_resolves_to_that_registered_project(self):
        target = self._svc("blueprints").target_repo(self.store.get_node(self.item))

        self.assertEqual(target, os.path.join(self.projects_root, "blueprints"))

    def test_the_default_workspace_still_uses_the_items_own_repo(self):
        target = self._svc("project").target_repo(self.store.get_node(self.item))

        self.assertEqual(target, os.path.join(self.projects_root, "saga"))

    def test_specs_resolves_through_the_project_registry_like_any_named_workspace(self):
        target = self._svc("specs").target_repo(self.store.get_node(self.item))

        self.assertEqual(target, "/specs")

    def test_an_unregistered_workspace_name_fails_rather_than_silently_using_the_item_repo(self):
        with self.assertRaises(UseCaseError):
            self._svc("not-a-project").target_repo(self.store.get_node(self.item))

    def test_a_named_workspace_needs_no_repo_artifact_on_the_item(self):
        bare = self.store.create_item("no repo", "a description")

        target = self._svc("blueprints").target_repo(self.store.get_node(bare))

        self.assertEqual(target, os.path.join(self.projects_root, "blueprints"))


class _TwoPhaseFlow:
    _PHASES = {"spec-handle-feedback": "spec", "write-code": "code"}

    def workflow_for(self, node):
        return "spec-driven"

    def load_graph(self, name=None):
        return _Graph("project")

    def phase_for(self, node):
        return self._PHASES.get(getattr(node, "stage", None))

    def phase_for_stage(self, stage, name=None):
        return self._PHASES.get(stage)

    def workspace_for_phase(self, node, phase):
        return SPECS_WORKSPACE if phase == "spec" else "project"

    def workspace_for_node(self, node):
        return self.workspace_for_phase(node, self.phase_for(node))


class TestClaimResolvesFromTheClaimedStep(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.specs = os.path.join(self.root, "specs")
        self.repo = os.path.join(self.root, "app")
        self.store.add_project(SPECS_WORKSPACE, local_path=self.specs)
        self.item = self.store.create_item("Login feature", "a description")
        self.store.add_artifact(self.item, "repo", self.repo)
        self.feedback = self._step("spec-handle-feedback")
        self.code = self._step("write-code")
        self.git = FakeGit(repos={self.specs, self.repo}, sync_result=True, base="origin/main")
        self.svc = WorktreeService(
            self.store, self.git, FakeFs(), _Cfg(self.root),
            flow=_TwoPhaseFlow(), scaffold=ScaffoldAdapter(),
        )

    def _step(self, stage):
        sid = self.store.create_step(step=stage, parent=self.item)
        PassBook(self.store, _TwoPhaseFlow()).enrol(self.item, sid, stage)
        return self.store.get_node(sid)

    def _branches(self):
        return {r.phase: r.branch for r in self.store.runs_of(self.item)}

    def test_claiming_the_later_code_step_yields_the_code_worktree_and_branch(self):
        runs_before = len(self.store.runs_of(self.item))

        path = self.svc.ensure(self.code)

        self.assertEqual(path, os.path.join(self.repo, ".worktrees", "%s-code" % self.item))
        self.assertEqual(self.svc.item_branch(self.code), self._branches()["code"])
        self.assertIn("code", self._branches()["code"])
        self.assertIsNone(self._branches()["spec"])
        self.assertEqual(len(self.store.runs_of(self.item)), runs_before)

    def test_claiming_the_first_spec_step_yields_the_specs_worktree_and_run(self):
        path = self.svc.ensure(self.feedback)

        self.assertEqual(path, os.path.join(self.specs, ".worktrees", "%s-spec" % self.item))
        self.assertIsNotNone(self._branches()["spec"])
        self.assertIsNone(self._branches()["code"])

    def test_the_claimed_step_is_the_only_open_step(self):
        self.store.update_state(self.feedback.id, State.DONE)

        path = self.svc.ensure(self.code)

        self.assertEqual(path, os.path.join(self.repo, ".worktrees", "%s-code" % self.item))

    def test_the_claimed_step_is_first_in_child_order(self):
        path = self.svc.ensure(self.feedback)

        self.assertEqual(os.path.dirname(os.path.dirname(path)), self.specs)


class TestWorktreesOf(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        self.store.add_project(SPECS_WORKSPACE, local_path="/specs")
        self.item = self.store.create_item("Login feature", "a description")

    def _svc(self):
        return WorktreeService(
            self.store, git=None, fs=None, config=_Cfg("/projects"), flow=_TwoPhaseFlow()
        )

    def test_a_mixed_item_returns_one_pair_per_run_with_a_branch(self):
        self.store.add_artifact(self.item, "repo", "/elsewhere/app")
        plant_run(self.store, self.item, "spec", "spec/x")
        plant_run(self.store, self.item, "code", "feat/y")
        plant_run(self.store, self.item, "spec", None, n=2)

        pairs = self._svc().worktrees_of(self.item)

        self.assertEqual(
            pairs,
            [
                ("/specs", os.path.join("/specs", ".worktrees", "%s-spec" % self.item)),
                ("/elsewhere/app", os.path.join("/elsewhere/app", ".worktrees", "%s-code" % self.item)),
            ],
        )

    def test_a_repo_less_item_keeps_its_specs_run_and_drops_a_project_run(self):
        plant_run(self.store, self.item, "spec", "spec/x")
        plant_run(self.store, self.item, "code", "feat/y")

        pairs = self._svc().worktrees_of(self.item)

        self.assertEqual(
            pairs, [("/specs", os.path.join("/specs", ".worktrees", "%s-spec" % self.item))]
        )

    def test_all_branchless_runs_return_nothing(self):
        self.store.add_artifact(self.item, "repo", "/elsewhere/app")
        plant_run(self.store, self.item, "spec")
        plant_run(self.store, self.item, "code")

        self.assertEqual(self._svc().worktrees_of(self.item), [])

    def test_remove_releases_the_specs_and_code_runs_whichever_step_is_open(self):
        self.store.add_artifact(self.item, "repo", "/elsewhere/app")
        plant_run(self.store, self.item, "spec", "spec/x")
        plant_run(self.store, self.item, "code", "feat/y")
        self.store.create_step(step="spec-handle-feedback", parent=self.item)
        git = FakeGit(repos={"/specs", "/elsewhere/app"})

        WorktreeService(
            self.store, git, fs=None, config=_Cfg("/projects"), flow=_TwoPhaseFlow()
        ).remove(self.item)

        self.assertIn(("delete_branch", "/specs", "spec/x"), git.calls)
        self.assertIn(("delete_branch", "/elsewhere/app", "feat/y"), git.calls)
