import subprocess
import tempfile
import unittest
from pathlib import Path

from lightcycle.adapters.fsio import FsAdapter
from lightcycle.adapters.gitio import GitAdapter
from lightcycle.adapters.sqlite_store import SqliteStore
from lightcycle.application.errors import UseCaseError
from lightcycle.application.setup import (
    AddProjectInput,
    AddProjectUseCase,
    ListProjectsUseCase,
    RemoveProjectUseCase,
)
from lightcycle.config import Config


def _env(with_store=True, with_workflows=True):
    root = tempfile.mkdtemp()
    projects = tempfile.mkdtemp()
    if with_store:
        Path(root, "store.db").touch()
    if with_workflows:
        Path(root, "workflows").mkdir()
    cfg = Path(tempfile.mkdtemp()) / "config"
    cfg.write_text(
        "projects: %s\nspecs: %s\nshortcode: xy\ndefault-workflow: standard\n"
        % (projects, projects)
    )
    config = Config(environ={"LC_HOME": root, "LC_CONFIG": str(cfg)})
    return config, FsAdapter(config), projects


def _store(config):
    return SqliteStore(config)


def _repo_with_origin(remote_url="git@github.com:acme/ghost.git"):
    d = tempfile.mkdtemp()
    subprocess.run(["git", "init", "-q", d], check=True)
    subprocess.run(["git", "-C", d, "remote", "add", "origin", remote_url], check=True)
    return d


class TestAddProject(unittest.TestCase):
    def test_registers_a_project_in_the_registry(self):
        config, fs, projects = _env()
        store = _store(config)
        r = AddProjectUseCase(store, GitAdapter(), config, fs).execute(
            AddProjectInput(identity="acme/myproj")
        )
        self.assertEqual(r.shortcode, "MYPROJ")
        self.assertTrue(r.changed)
        self.assertIsNone(r.local_path)
        self.assertIsNone(r.remote)
        self.assertEqual(store.get_project("acme/myproj").shortcode, "MYPROJ")

    def test_is_idempotent(self):
        config, fs, _ = _env()
        uc = AddProjectUseCase(_store(config), GitAdapter(), config, fs)
        uc.execute(AddProjectInput(identity="acme/myproj"))
        r = uc.execute(AddProjectInput(identity="acme/myproj"))
        self.assertFalse(r.changed)
        self.assertEqual(r.shortcode, "MYPROJ")

    def test_explicit_shortcode_overrides_and_is_idempotent_when_repeated(self):
        config, fs, _ = _env()
        uc = AddProjectUseCase(_store(config), GitAdapter(), config, fs)
        uc.execute(AddProjectInput(identity="acme/myproj"))
        r = uc.execute(AddProjectInput(identity="acme/myproj", shortcode="CUSTOM"))
        self.assertTrue(r.changed)
        self.assertEqual(r.shortcode, "CUSTOM")
        r2 = uc.execute(AddProjectInput(identity="acme/myproj", shortcode="CUSTOM"))
        self.assertFalse(r2.changed)

    def test_refuses_when_store_not_initialised(self):
        config, fs, _ = _env(with_store=False)
        with self.assertRaises(UseCaseError):
            AddProjectUseCase(None, GitAdapter(), config, fs).execute(
                AddProjectInput(identity="acme/myproj")
            )

    def test_registers_a_project_with_a_path_that_does_not_exist_on_disk(self):
        config, fs, _ = _env()
        r = AddProjectUseCase(_store(config), GitAdapter(), config, fs).execute(
            AddProjectInput(identity="acme/ghost", path="/does/not/exist")
        )
        self.assertEqual(r.local_path, "/does/not/exist")
        self.assertIsNone(r.remote)

    def test_refuses_an_identity_without_owner_slash_name_shape(self):
        config, fs, _ = _env()
        with self.assertRaises(UseCaseError) as ctx:
            AddProjectUseCase(_store(config), GitAdapter(), config, fs).execute(
                AddProjectInput(identity="not-owner-slash-name")
            )
        self.assertIn("not-owner-slash-name", str(ctx.exception))

    def test_path_pointing_at_a_real_repo_records_its_origin_remote(self):
        config, fs, _ = _env()
        repo = _repo_with_origin("git@github.com:acme/ghost.git")
        r = AddProjectUseCase(_store(config), GitAdapter(), config, fs).execute(
            AddProjectInput(identity="acme/ghost", path=repo)
        )
        self.assertEqual(r.local_path, repo)
        self.assertEqual(r.remote, "git@github.com:acme/ghost.git")


class TestListProjects(unittest.TestCase):
    def test_list_returns_every_registered_entry(self):
        config, fs, _ = _env()
        store = _store(config)
        AddProjectUseCase(store, GitAdapter(), config, fs).execute(
            AddProjectInput(identity="acme/horde")
        )
        AddProjectUseCase(store, GitAdapter(), config, fs).execute(
            AddProjectInput(identity="acme/saga")
        )
        identities = {p.identity for p in ListProjectsUseCase(store).execute()}
        self.assertEqual(identities, {"acme/horde", "acme/saga"})


class TestRemoveProject(unittest.TestCase):
    def test_remove_deletes_the_entry(self):
        config, fs, _ = _env()
        store = _store(config)
        AddProjectUseCase(store, GitAdapter(), config, fs).execute(
            AddProjectInput(identity="acme/horde")
        )
        RemoveProjectUseCase(store).execute("acme/horde")
        self.assertIsNone(store.get_project("acme/horde"))

    def test_remove_of_an_unknown_identity_raises_use_case_error(self):
        config, fs, _ = _env()
        store = _store(config)
        with self.assertRaises(UseCaseError):
            RemoveProjectUseCase(store).execute("acme/ghost")
