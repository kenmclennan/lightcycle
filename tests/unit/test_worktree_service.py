import os
import unittest

from lightcycle.application.errors import UseCaseError
from lightcycle.application.services.worktree import WorktreeService
from tests.support.fake_store import FakeStore


class _Cfg:
    def __init__(self, projects_root, engine_root="lightcycle", specs_root="/specs"):
        self._projects_root = projects_root
        self._engine_root = engine_root
        self._specs_root = specs_root

    def projects_root(self):
        return self._projects_root

    def specs_root(self):
        return self._specs_root

    def engine_root(self):
        return self._engine_root


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


class _Graph:
    def __init__(self, workspace):
        self.workspace = workspace


class _FakeGit:
    def __init__(self, git_repos=()):
        self._git_repos = set(git_repos)
        self.calls = []

    def is_git_repo(self, path):
        self.calls.append(("is_git_repo", path))
        return path in self._git_repos


class TestWorktreePath(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        self.svc = WorktreeService(
            self.store, git=None, fs=None, config=_Cfg("/home/u/workspace/projects")
        )

    def test_resolves_under_the_items_target_repo_not_data_root(self):
        theme = self.store.create_theme("theme")
        item = self.store.create_item("story", theme=theme)
        self.store.add_artifact(item, "repo", "saga")

        path = self.svc.worktree_path(item)

        self.assertEqual(
            path, os.path.join("/home/u/workspace/projects", "saga", ".worktrees", item)
        )

    def test_two_items_with_different_repos_resolve_under_their_own_repos(self):
        theme = self.store.create_theme("theme")
        saga_item = self.store.create_item("saga story", theme=theme)
        self.store.add_artifact(saga_item, "repo", "saga")
        horde_item = self.store.create_item("horde story", theme=theme)
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


class TestItemRepoNoFallback(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        self.svc = WorktreeService(
            self.store, git=None, fs=None, config=_Cfg("/home/u/workspace/projects")
        )

    def test_item_repo_returns_explicit_artifact(self):
        theme = self.store.create_theme("theme")
        item = self.store.create_item("story", theme=theme)
        self.store.add_artifact(item, "repo", "saga")

        self.assertEqual(self.svc.item_repo(item), "saga")

    def test_item_repo_raises_when_no_repo_artifact(self):
        theme = self.store.create_theme("theme")
        item = self.store.create_item("story", theme=theme)

        with self.assertRaises(UseCaseError):
            self.svc.item_repo(item)

    def test_has_repo_reflects_artifact_presence(self):
        theme = self.store.create_theme("theme")
        item = self.store.create_item("story", theme=theme)

        self.assertFalse(self.svc.has_repo(item))
        self.store.add_artifact(item, "repo", "saga")
        self.assertTrue(self.svc.has_repo(item))


class TestSpecsWorkspace(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()

    def test_target_repo_is_specs_root_when_workflow_sources_from_specs(self):
        theme = self.store.create_theme("theme")
        item = self.store.create_item("spec item", theme=theme)
        svc = WorktreeService(
            self.store, git=None, fs=None,
            config=_Cfg("/home/u/workspace/projects"), flow=_FakeFlow(workspace="specs"),
        )

        self.assertEqual(svc.target_repo(item), "/specs")

    def test_target_repo_is_projects_root_repo_when_workflow_omits_workspace(self):
        theme = self.store.create_theme("theme")
        item = self.store.create_item("story", theme=theme)
        self.store.add_artifact(item, "repo", "saga")
        svc = WorktreeService(
            self.store, git=None, fs=None,
            config=_Cfg("/home/u/workspace/projects"), flow=_FakeFlow(workspace="project"),
        )

        self.assertEqual(
            svc.target_repo(item), os.path.join("/home/u/workspace/projects", "saga")
        )

    def test_target_repo_without_a_flow_falls_back_to_project(self):
        theme = self.store.create_theme("theme")
        item = self.store.create_item("story", theme=theme)
        self.store.add_artifact(item, "repo", "saga")
        svc = WorktreeService(
            self.store, git=None, fs=None, config=_Cfg("/home/u/workspace/projects")
        )

        self.assertEqual(
            svc.target_repo(item), os.path.join("/home/u/workspace/projects", "saga")
        )

    def test_ensure_does_not_silently_skip_specs_workspace_without_a_repo_artifact(self):
        theme = self.store.create_theme("theme")
        item = self.store.create_item("spec item", theme=theme)
        git = _FakeGit()
        svc = WorktreeService(
            self.store, git, fs=None, config=_Cfg("/home/u/workspace/projects"),
            flow=_FakeFlow(workspace="specs"),
        )

        with self.assertRaises(UseCaseError):
            svc.ensure(item)
        self.assertIn(("is_git_repo", "/specs"), git.calls)

    def test_remove_targets_specs_root_without_a_repo_artifact(self):
        theme = self.store.create_theme("theme")
        item = self.store.create_item("spec item", theme=theme)
        git = _FakeGit()
        svc = WorktreeService(
            self.store, git, fs=None, config=_Cfg("/home/u/workspace/projects"),
            flow=_FakeFlow(workspace="specs"),
        )

        svc.remove(item)

        self.assertEqual(git.calls, [("is_git_repo", "/specs")])


class TestPhaseLabelledBranch(unittest.TestCase):
    def test_item_branch_ignores_a_branch_labelled_for_a_different_phase(self):
        store = FakeStore()
        theme = store.create_theme("theme")
        item = store.create_item("spec item", theme=theme)
        store.add_artifact(item, "branch", "spec/x", label="spec")
        svc = WorktreeService(
            store, git=None, fs=None, config=_Cfg("/projects"), flow=_FakeFlow(workspace="project")
        )

        self.assertIsNone(svc.item_branch(item))

    def test_item_branch_matches_the_current_phase_label(self):
        store = FakeStore()
        theme = store.create_theme("theme")
        item = store.create_item("spec item", theme=theme)
        store.add_artifact(item, "branch", "spec/x", label="spec")
        store.add_artifact(item, "branch", "feat/x", label="code")
        svc = WorktreeService(
            store, git=None, fs=None, config=_Cfg("/projects"), flow=_FakeFlow(workspace="project")
        )

        self.assertEqual(svc.item_branch(item), "feat/x")

    def test_ensure_branch_artifact_labels_the_new_branch_with_the_current_phase(self):
        store = FakeStore()
        theme = store.create_theme("theme")
        item = store.create_item("code item", theme=theme)
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
        theme = self.store.create_theme("theme")
        item = self.store.create_item("story", theme=theme)
        git = _FakeGit()
        svc = WorktreeService(self.store, git, fs=None, config=_Cfg("/projects"))

        self.assertIsNone(svc.ensure(item))
        self.assertEqual(git.calls, [])

    def test_ensure_raises_when_repo_present_but_not_a_git_repo(self):
        theme = self.store.create_theme("theme")
        item = self.store.create_item("story", theme=theme)
        self.store.add_artifact(item, "repo", "saga")
        git = _FakeGit(git_repos=())
        svc = WorktreeService(self.store, git, fs=None, config=_Cfg("/projects"))

        with self.assertRaises(UseCaseError):
            svc.ensure(item)


if __name__ == "__main__":
    unittest.main()
