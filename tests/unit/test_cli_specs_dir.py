import io
import unittest
from contextlib import redirect_stderr, redirect_stdout

import lightcycle.cli as cli_mod
from lightcycle.cli import cmd_specs_dir
from lightcycle.container import Container
from tests.support.fake_git import FakeGit
from tests.support.fake_store import FakeStore


class FakeConfig:
    def __init__(self, project="specs"):
        self._project = project

    def context_artifact_project(self):
        return self._project


class TestSpecsDirCheck(unittest.TestCase):
    def setUp(self):
        self._orig = cli_mod._container
        self.addCleanup(lambda: cli_mod.set_container(self._orig))

    def _run(self, store, git):
        cli_mod.set_container(Container(
            config=FakeConfig(), git=git, store=store, spawner=object(), workers=object(),
            fs=object(), github=object(), lock=object(), breaker=object(),
        ))
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = cmd_specs_dir(["--check"]) or 0
        return rc, out.getvalue(), err.getvalue()

    def _store(self, path="/specs", remote="git@github.com:x/specs.git"):
        store = FakeStore()
        store.add_project("specs", local_path=path, remote=remote)
        return store

    def test_passes_when_origin_matches_specs_remote(self):
        rc, out, err = self._run(self._store(), FakeGit(origin="git@github.com:x/specs.git"))
        self.assertEqual(rc, 0, err)
        self.assertIn("ok", out)
        self.assertIn("/specs", out)

    def test_fails_when_not_a_git_repo(self):
        rc, out, err = self._run(self._store(), FakeGit(is_repo=False))
        self.assertEqual(rc, 1)
        self.assertIn("not a git repo", err)

    def test_fails_when_origin_does_not_match(self):
        rc, out, err = self._run(self._store(), FakeGit(origin="git@github.com:other/repo.git"))
        self.assertEqual(rc, 1)
        self.assertIn("does not match specs-remote", err)

    def test_fails_when_specs_remote_missing(self):
        rc, out, err = self._run(self._store(remote=None), FakeGit())
        self.assertEqual(rc, 1)
        self.assertIn("no remote registered", err)

    def test_fails_when_no_specs_project_registered(self):
        rc, out, err = self._run(FakeStore(), FakeGit())
        self.assertEqual(rc, 1)
        self.assertIn("no 'specs' project registered", err)

    def test_bare_specs_dir_unchanged_by_check_support(self):
        cli_mod.set_container(Container(
            config=FakeConfig(), git=FakeGit(), store=self._store(), spawner=object(),
            workers=object(), fs=object(), github=object(), lock=object(), breaker=object(),
        ))
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = cmd_specs_dir([]) or 0
        self.assertEqual(rc, 0, err.getvalue())
        self.assertEqual(out.getvalue().strip(), "/specs")


class TestSpecsDirHonoursConfiguredProject(unittest.TestCase):
    def test_resolves_the_project_named_by_config(self):
        store = FakeStore()
        store.add_project("docs", local_path="/docs-root")
        orig = cli_mod._container
        self.addCleanup(lambda: cli_mod.set_container(orig))
        cli_mod.set_container(Container(
            config=FakeConfig("docs"), git=FakeGit(), store=store, spawner=object(),
            workers=object(), fs=object(), github=object(), lock=object(), breaker=object(),
        ))
        out = io.StringIO()
        with redirect_stdout(out):
            rc = cmd_specs_dir([]) or 0
        self.assertEqual((rc, out.getvalue().strip()), (0, "/docs-root"))


if __name__ == "__main__":
    unittest.main()
