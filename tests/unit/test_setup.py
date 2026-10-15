import unittest

from lightcycle.application.setup import InitGridUseCase
from lightcycle.application.errors import UseCaseError
from lightcycle.domain.flow.flow import GUIDANCE_WORKSPACE, SPECS_WORKSPACE
from lightcycle.config import ConfigError
from tests.support.fake_git import FakeGit
from tests.support.fake_github import FakeGitHub
from tests.support.fake_fs import FakeFs
from tests.support.fake_store import FakeStore


class FakeConfig:
    def __init__(self, created=True, legacy=None, trusted=None):
        self._created = created
        self._legacy = legacy or {}
        self.trusted = trusted

    def trusted_authors(self):
        if not self.trusted:
            raise ConfigError("trusted-authors is not set")
        return frozenset(self.trusted.split())

    def seed_trusted_authors(self, login):
        self.trusted = login

    def ensure_config(self):
        return self._created

    def config_path(self):
        return "/cfg/lightcycle/config"

    def load_config(self):
        return self._legacy

    def expand_path(self, v):
        return v


def _init_grid(store, fs, config, git, github=None):
    return InitGridUseCase(store, fs, config, git, github if github is not None else FakeGitHub())


class TestInitGrid(unittest.TestCase):
    def test_reports_existed_created_and_path(self):
        r = _init_grid(FakeStore(), FakeFs(), FakeConfig(created=True), FakeGit()).execute()
        self.assertTrue(r.existed)
        self.assertTrue(r.created)
        self.assertEqual(r.config_path, "/cfg/lightcycle/config")

    def test_created_false_when_config_present(self):
        r = _init_grid(FakeStore(), FakeFs(), FakeConfig(created=False), FakeGit()).execute()
        self.assertFalse(r.created)

    def test_registers_a_default_specs_project_when_none_is_registered(self):
        store = FakeStore()
        _init_grid(store, FakeFs(), FakeConfig(), FakeGit()).execute()
        project = store.get_project(SPECS_WORKSPACE)
        self.assertEqual(project.local_path, "~/workspace/specs")
        self.assertIsNone(project.remote)

    def test_migrates_a_legacy_specs_config_into_the_project_registry(self):
        store = FakeStore()
        config = FakeConfig(legacy={"specs": "/old/specs", "specs-remote": "git@x:specs.git"})
        _init_grid(store, FakeFs(), config, FakeGit()).execute()
        project = store.get_project(SPECS_WORKSPACE)
        self.assertEqual(project.local_path, "/old/specs")
        self.assertEqual(project.remote, "git@x:specs.git")

    def test_leaves_an_already_registered_specs_project_untouched(self):
        store = FakeStore()
        store.add_project(SPECS_WORKSPACE, local_path="/existing", remote="git@x:existing.git")
        _init_grid(store, FakeFs(), FakeConfig(), FakeGit()).execute()
        project = store.get_project(SPECS_WORKSPACE)
        self.assertEqual(project.local_path, "/existing")
        self.assertEqual(project.remote, "git@x:existing.git")


class TestInitSeedsTrustedAuthors(unittest.TestCase):
    def test_a_blank_key_is_seeded_from_the_gh_login(self):
        config = FakeConfig()
        r = _init_grid(FakeStore(), FakeFs(), config, FakeGit(), FakeGitHub(login="ken")).execute()
        self.assertEqual(config.trusted, "ken")
        self.assertEqual(r.trusted_authors_seeded, "ken")
        self.assertEqual(r.trusted_authors_unset_reason, "")

    def test_a_non_blank_key_is_never_overwritten(self):
        config = FakeConfig(trusted="alice bob")
        r = _init_grid(FakeStore(), FakeFs(), config, FakeGit(), FakeGitHub(login="ken")).execute()
        self.assertEqual(config.trusted, "alice bob")
        self.assertEqual(r.trusted_authors_seeded, "")

    def test_a_failed_gh_read_leaves_the_key_blank_and_reports_why(self):
        config = FakeConfig()
        github = FakeGitHub(failing_calls={"authenticated_login"})
        r = _init_grid(FakeStore(), FakeFs(), config, FakeGit(), github).execute()
        self.assertIsNone(config.trusted)
        self.assertEqual(r.trusted_authors_seeded, "")
        self.assertEqual(r.trusted_authors_unset_reason, "boom")


class TestInitGuidanceRepo(unittest.TestCase):
    def _run(self, store=None, fs=None, git=None, path=None):
        store = store or FakeStore()
        fs = fs or FakeFs()
        git = git or FakeGit()
        r = _init_grid(store, fs, FakeConfig(), git).execute(path)
        return r, store, fs, git

    def test_skeleton_says_guidance_repo_and_commits_with_that_subject(self):
        from lightcycle.domain.guidance import conventions, skeleton

        self.assertEqual(skeleton.COMMIT_MESSAGE, "chore: add the guidance repo skeleton")
        self.assertIn("guidance repo", skeleton.INDEX_TEXT.lower())
        self.assertNotIn("knowledge base", skeleton.INDEX_TEXT.lower())
        self.assertNotIn("knowledge base", conventions.CONVENTIONS_TEXT.lower())

    def test_the_old_verb_and_flag_are_gone(self):
        from lightcycle.cli_commands import COMMANDS

        self.assertNotIn("knowledge-dir", COMMANDS)
        self.assertIn("guidance-dir", COMMANDS)
        flags = [a.flags if hasattr(a, "flags") else a for a in COMMANDS["init"].args]
        self.assertNotIn("--knowledge-path", str(flags))

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
            ["~/workspace/agent-guidance/index.md", "~/workspace/agent-guidance/CONVENTIONS.md"],
        )
        project = store.get_project(GUIDANCE_WORKSPACE)
        self.assertEqual(project.local_path, "~/workspace/agent-guidance")
        self.assertIsNone(project.remote)
        self.assertEqual(r.guidance_outcome, "created")
        self.assertEqual(r.guidance_path, "~/workspace/agent-guidance")

    def test_missing_identity_does_the_rest_and_reports_the_guidance_repo_uncreated(self):
        git = FakeGit(missing_identity=["user.name", "user.email"])
        r, store, fs, git = self._run(git=git)
        self.assertEqual(r.guidance_outcome, "not created")
        self.assertIn('git config --global user.name "<name>"', r.guidance_refusal)
        self.assertIn('git config --global user.email "<email>"', r.guidance_refusal)
        self.assertIsNone(store.get_project(GUIDANCE_WORKSPACE))
        self.assertIsNotNone(store.get_project(SPECS_WORKSPACE))
        self.assertEqual(fs.writes, [])
        self.assertNotIn("init_repo", self._call_names(git))

    def test_rerun_after_configuring_identity_creates_the_guidance_repo(self):
        store = FakeStore()
        fs = FakeFs()
        _init_grid(store, fs, FakeConfig(), FakeGit(missing_identity=["user.name"])).execute()
        r = _init_grid(store, fs, FakeConfig(), FakeGit()).execute()
        self.assertEqual(r.guidance_outcome, "created")
        self.assertEqual(r.guidance_refusal, "")
        self.assertIsNotNone(store.get_project(GUIDANCE_WORKSPACE))

    def test_missing_identity_does_not_block_registering_an_existing_repo(self):
        fs = FakeFs(dirs={"/kb": []})
        git = FakeGit(repos={"/kb"}, missing_identity=["user.name", "user.email"])
        r, store, fs, git = self._run(fs=fs, git=git, path="/kb")
        self.assertEqual(r.guidance_outcome, "registered")

    def test_missing_identity_does_not_block_an_already_registered_guidance_repo(self):
        store = FakeStore()
        store.add_project(GUIDANCE_WORKSPACE, local_path="/kb", remote=None)
        git = FakeGit(missing_identity=["user.name"])
        r, store, fs, git = self._run(store=store, git=git)
        self.assertEqual(r.guidance_outcome, "unchanged")

    def test_repo_root_path_is_registered_with_its_origin_and_not_written_to(self):
        fs = FakeFs(dirs={"/kb": []})
        git = FakeGit(repos={"/kb"}, origin="git@x:kb.git")
        r, store, fs, git = self._run(fs=fs, git=git, path="/kb")
        project = store.get_project(GUIDANCE_WORKSPACE)
        self.assertEqual(project.local_path, "/kb")
        self.assertEqual(project.remote, "git@x:kb.git")
        self.assertEqual(fs.writes, [])
        self.assertNotIn("commit_all", self._call_names(git))
        self.assertEqual(r.guidance_outcome, "registered")

    def test_existing_directory_that_is_not_a_repo_root_is_refused_naming_the_path(self):
        fs = FakeFs(dirs={"/kb": []})
        git = FakeGit(repos=set())
        store = FakeStore()
        with self.assertRaises(UseCaseError) as caught:
            _init_grid(store, fs, FakeConfig(), git).execute("/kb")
        self.assertIn("/kb", str(caught.exception))
        self.assertIsNone(store.get_project(GUIDANCE_WORKSPACE))
        self.assertEqual(fs.writes, [])

    def test_directory_inside_another_repo_without_its_own_git_dir_is_refused(self):
        fs = FakeFs(dirs={"/outer/kb": []})
        git = FakeGit(repos={"/outer"}, is_repo=True)
        store = FakeStore()
        with self.assertRaises(UseCaseError):
            _init_grid(store, fs, FakeConfig(), git).execute("/outer/kb")
        self.assertIsNone(store.get_project(GUIDANCE_WORKSPACE))

    def test_already_registered_makes_no_git_or_fs_call(self):
        store = FakeStore()
        store.add_project(GUIDANCE_WORKSPACE, local_path="/kb", remote=None)
        fs, git = FakeFs(), FakeGit()
        r = _init_grid(store, fs, FakeConfig(), git).execute()
        self.assertEqual(git.calls, [])
        self.assertEqual(fs.writes, [])
        self.assertEqual(r.guidance_outcome, "unchanged")
        self.assertEqual(r.guidance_path, "/kb")

    def test_registered_path_that_no_longer_exists_is_not_recreated(self):
        store = FakeStore()
        store.add_project(GUIDANCE_WORKSPACE, local_path="/gone", remote=None)
        fs, git = FakeFs(), FakeGit()
        self.assertEqual(self._run(store, fs, git, path="/gone")[0].guidance_outcome, "unchanged")
        self.assertEqual(git.calls, [])

    def test_registered_with_a_different_flag_refuses_naming_both_paths(self):
        store = FakeStore()
        store.add_project(GUIDANCE_WORKSPACE, local_path="/kb", remote=None)
        with self.assertRaises(UseCaseError) as caught:
            _init_grid(store, FakeFs(), FakeConfig(), FakeGit()).execute("/other")
        self.assertIn("/kb", str(caught.exception))
        self.assertIn("/other", str(caught.exception))
        self.assertEqual(store.get_project(GUIDANCE_WORKSPACE).local_path, "/kb")

    def test_failed_git_init_refuses_and_registers_nothing(self):
        store = FakeStore()
        with self.assertRaises(UseCaseError) as caught:
            _init_grid(store, FakeFs(), FakeConfig(), FakeGit(init_ok=False)).execute()
        self.assertIn("~/workspace/agent-guidance", str(caught.exception))
        self.assertIsNone(store.get_project(GUIDANCE_WORKSPACE))

    def test_failed_commit_refuses_and_registers_nothing(self):
        store = FakeStore()
        with self.assertRaises(UseCaseError) as caught:
            _init_grid(store, FakeFs(), FakeConfig(), FakeGit(commit_ok=False)).execute()
        self.assertIn("remove it", str(caught.exception))
        self.assertIsNone(store.get_project(GUIDANCE_WORKSPACE))

    def test_the_flag_overrides_the_default_path(self):
        r, store, fs, git = self._run(path="/elsewhere/kb")
        self.assertEqual(store.get_project(GUIDANCE_WORKSPACE).local_path, "/elsewhere/kb")
        self.assertEqual(fs.writes[0], "/elsewhere/kb/index.md")


if __name__ == "__main__":
    unittest.main()
