import unittest

from lightcycle.application.setup import InitGridUseCase
from lightcycle.application.errors import UseCaseError
from lightcycle.domain.flow.flow import KNOWLEDGE_WORKSPACE, SPECS_WORKSPACE
from tests.support.fake_git import FakeGit
from tests.support.fake_fs import FakeFs
from tests.support.fake_store import FakeStore


class FakeConfig:
    def __init__(self, created=True, legacy=None):
        self._created = created
        self._legacy = legacy or {}

    def ensure_config(self):
        return self._created

    def config_path(self):
        return "/cfg/lightcycle/config"

    def load_config(self):
        return self._legacy

    def expand_path(self, v):
        return v


class TestInitGrid(unittest.TestCase):
    def test_reports_existed_created_and_path(self):
        r = InitGridUseCase(FakeStore(), FakeFs(), FakeConfig(created=True), FakeGit()).execute()
        self.assertTrue(r.existed)
        self.assertTrue(r.created)
        self.assertEqual(r.config_path, "/cfg/lightcycle/config")

    def test_created_false_when_config_present(self):
        r = InitGridUseCase(FakeStore(), FakeFs(), FakeConfig(created=False), FakeGit()).execute()
        self.assertFalse(r.created)

    def test_registers_a_default_specs_project_when_none_is_registered(self):
        store = FakeStore()
        InitGridUseCase(store, FakeFs(), FakeConfig(), FakeGit()).execute()
        project = store.get_project(SPECS_WORKSPACE)
        self.assertEqual(project.local_path, "~/workspace/specs")
        self.assertIsNone(project.remote)

    def test_migrates_a_legacy_specs_config_into_the_project_registry(self):
        store = FakeStore()
        config = FakeConfig(legacy={"specs": "/old/specs", "specs-remote": "git@x:specs.git"})
        InitGridUseCase(store, FakeFs(), config, FakeGit()).execute()
        project = store.get_project(SPECS_WORKSPACE)
        self.assertEqual(project.local_path, "/old/specs")
        self.assertEqual(project.remote, "git@x:specs.git")

    def test_leaves_an_already_registered_specs_project_untouched(self):
        store = FakeStore()
        store.add_project(SPECS_WORKSPACE, local_path="/existing", remote="git@x:existing.git")
        InitGridUseCase(store, FakeFs(), FakeConfig(), FakeGit()).execute()
        project = store.get_project(SPECS_WORKSPACE)
        self.assertEqual(project.local_path, "/existing")
        self.assertEqual(project.remote, "git@x:existing.git")


class TestInitKnowledgeBase(unittest.TestCase):
    def _run(self, store=None, fs=None, git=None, path=None):
        store = store or FakeStore()
        fs = fs or FakeFs()
        git = git or FakeGit()
        r = InitGridUseCase(store, fs, FakeConfig(), git).execute(path)
        return r, store, fs, git

    def _call_names(self, git):
        return [c[0] for c in git.calls]

    def test_absent_path_is_created_with_the_skeleton_in_one_commit_and_registered(self):
        r, store, fs, git = self._run()
        names = self._call_names(git)
        self.assertEqual(names.count("init_repo"), 1)
        self.assertEqual(names.count("commit_all"), 1)
        self.assertLess(names.index("init_repo"), names.index("commit_all"))
        self.assertEqual(
            fs.writes,
            ["~/workspace/knowledge/index.md", "~/workspace/knowledge/CONVENTIONS.md"],
        )
        project = store.get_project(KNOWLEDGE_WORKSPACE)
        self.assertEqual(project.local_path, "~/workspace/knowledge")
        self.assertIsNone(project.remote)
        self.assertEqual(r.knowledge_outcome, "created")
        self.assertEqual(r.knowledge_path, "~/workspace/knowledge")

    def test_repo_root_path_is_registered_with_its_origin_and_not_written_to(self):
        fs = FakeFs(dirs={"/kb": []})
        git = FakeGit(repos={"/kb"}, origin="git@x:kb.git")
        r, store, fs, git = self._run(fs=fs, git=git, path="/kb")
        project = store.get_project(KNOWLEDGE_WORKSPACE)
        self.assertEqual(project.local_path, "/kb")
        self.assertEqual(project.remote, "git@x:kb.git")
        self.assertEqual(fs.writes, [])
        self.assertNotIn("commit_all", self._call_names(git))
        self.assertEqual(r.knowledge_outcome, "registered")

    def test_existing_directory_that_is_not_a_repo_root_is_refused_naming_the_path(self):
        fs = FakeFs(dirs={"/kb": []})
        git = FakeGit(repos=set())
        store = FakeStore()
        with self.assertRaises(UseCaseError) as caught:
            InitGridUseCase(store, fs, FakeConfig(), git).execute("/kb")
        self.assertIn("/kb", str(caught.exception))
        self.assertIsNone(store.get_project(KNOWLEDGE_WORKSPACE))
        self.assertEqual(fs.writes, [])

    def test_directory_inside_another_repo_without_its_own_git_dir_is_refused(self):
        fs = FakeFs(dirs={"/outer/kb": []})
        git = FakeGit(repos={"/outer"}, is_repo=True)
        store = FakeStore()
        with self.assertRaises(UseCaseError):
            InitGridUseCase(store, fs, FakeConfig(), git).execute("/outer/kb")
        self.assertIsNone(store.get_project(KNOWLEDGE_WORKSPACE))

    def test_already_registered_makes_no_git_or_fs_call(self):
        store = FakeStore()
        store.add_project(KNOWLEDGE_WORKSPACE, local_path="/kb", remote=None)
        fs, git = FakeFs(), FakeGit()
        r = InitGridUseCase(store, fs, FakeConfig(), git).execute()
        self.assertEqual(git.calls, [])
        self.assertEqual(fs.writes, [])
        self.assertEqual(r.knowledge_outcome, "unchanged")
        self.assertEqual(r.knowledge_path, "/kb")

    def test_registered_path_that_no_longer_exists_is_not_recreated(self):
        store = FakeStore()
        store.add_project(KNOWLEDGE_WORKSPACE, local_path="/gone", remote=None)
        fs, git = FakeFs(), FakeGit()
        self.assertEqual(self._run(store, fs, git, path="/gone")[0].knowledge_outcome, "unchanged")
        self.assertEqual(git.calls, [])

    def test_registered_with_a_different_flag_refuses_naming_both_paths(self):
        store = FakeStore()
        store.add_project(KNOWLEDGE_WORKSPACE, local_path="/kb", remote=None)
        with self.assertRaises(UseCaseError) as caught:
            InitGridUseCase(store, FakeFs(), FakeConfig(), FakeGit()).execute("/other")
        self.assertIn("/kb", str(caught.exception))
        self.assertIn("/other", str(caught.exception))
        self.assertEqual(store.get_project(KNOWLEDGE_WORKSPACE).local_path, "/kb")

    def test_failed_git_init_refuses_and_registers_nothing(self):
        store = FakeStore()
        with self.assertRaises(UseCaseError) as caught:
            InitGridUseCase(store, FakeFs(), FakeConfig(), FakeGit(init_ok=False)).execute()
        self.assertIn("~/workspace/knowledge", str(caught.exception))
        self.assertIsNone(store.get_project(KNOWLEDGE_WORKSPACE))

    def test_failed_commit_refuses_and_registers_nothing(self):
        store = FakeStore()
        with self.assertRaises(UseCaseError) as caught:
            InitGridUseCase(store, FakeFs(), FakeConfig(), FakeGit(commit_ok=False)).execute()
        self.assertIn("remove it", str(caught.exception))
        self.assertIsNone(store.get_project(KNOWLEDGE_WORKSPACE))

    def test_the_flag_overrides_the_default_path(self):
        r, store, fs, git = self._run(path="/elsewhere/kb")
        self.assertEqual(store.get_project(KNOWLEDGE_WORKSPACE).local_path, "/elsewhere/kb")
        self.assertEqual(fs.writes[0], "/elsewhere/kb/index.md")


if __name__ == "__main__":
    unittest.main()
