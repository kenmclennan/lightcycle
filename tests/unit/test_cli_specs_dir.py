import io
import unittest
from contextlib import redirect_stderr, redirect_stdout

import lightcycle.cli as cli_mod
from lightcycle.cli import cmd_specs_dir
from lightcycle.config import ConfigError
from lightcycle.container import Container


class FakeConfig:
    def __init__(self, specs="/specs", remote="git@github.com:x/specs.git", remote_missing=False):
        self._specs = specs
        self._remote = remote
        self._remote_missing = remote_missing

    def specs_root(self):
        return self._specs

    def specs_remote(self):
        if self._remote_missing:
            raise ConfigError("required config value 'specs-remote' is not set")
        return self._remote


class FakeGit:
    def __init__(self, is_repo=True, origin="git@github.com:x/specs.git"):
        self._is_repo = is_repo
        self._origin = origin

    def is_git_repo(self, root):
        return self._is_repo

    def remote_url(self, root):
        return self._origin


class TestSpecsDirCheck(unittest.TestCase):
    def setUp(self):
        self._orig = cli_mod._container
        self.addCleanup(lambda: cli_mod.set_container(self._orig))

    def _run(self, config, git):
        cli_mod.set_container(Container(
            config=config, git=git, store=object(), spawner=object(), workers=object(),
            fs=object(), github=object(), lock=object(), breaker=object(),
        ))
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = cmd_specs_dir(["--check"]) or 0
        return rc, out.getvalue(), err.getvalue()

    def test_passes_when_origin_matches_specs_remote(self):
        rc, out, err = self._run(FakeConfig(), FakeGit())
        self.assertEqual(rc, 0, err)
        self.assertIn("ok", out)
        self.assertIn("/specs", out)

    def test_fails_when_not_a_git_repo(self):
        rc, out, err = self._run(FakeConfig(), FakeGit(is_repo=False))
        self.assertEqual(rc, 1)
        self.assertIn("not a git repo", err)

    def test_fails_when_origin_does_not_match(self):
        rc, out, err = self._run(FakeConfig(), FakeGit(origin="git@github.com:other/repo.git"))
        self.assertEqual(rc, 1)
        self.assertIn("does not match specs-remote", err)

    def test_fails_when_specs_remote_config_missing(self):
        rc, out, err = self._run(FakeConfig(remote_missing=True), FakeGit())
        self.assertEqual(rc, 1)
        self.assertIn("specs-remote", err)

    def test_bare_specs_dir_unchanged_by_check_support(self):
        cli_mod.set_container(Container(
            config=FakeConfig(), git=FakeGit(), store=object(), spawner=object(),
            workers=object(), fs=object(), github=object(), lock=object(), breaker=object(),
        ))
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = cmd_specs_dir([]) or 0
        self.assertEqual(rc, 0, err.getvalue())
        self.assertEqual(out.getvalue().strip(), "/specs")


if __name__ == "__main__":
    unittest.main()
