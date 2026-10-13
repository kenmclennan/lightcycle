import io
import unittest
from contextlib import redirect_stderr, redirect_stdout

import lightcycle.cli as cli_mod
from lightcycle.cli import cmd_knowledge_dir
from lightcycle.container import Container
from lightcycle.domain.flow.flow import KNOWLEDGE_WORKSPACE
from tests.support.fake_git import FakeGit
from tests.support.fake_store import FakeStore


class TestKnowledgeDir(unittest.TestCase):
    def setUp(self):
        self._orig = cli_mod._container
        self.addCleanup(lambda: cli_mod.set_container(self._orig))

    def _run(self, store, git, argv):
        cli_mod.set_container(Container(
            config=object(), git=git, store=store, spawner=object(), workers=object(),
            fs=object(), github=object(), lock=object(), breaker=object(),
        ))
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = cmd_knowledge_dir(argv) or 0
        return rc, out.getvalue(), err.getvalue()

    def _store(self, path="/kb", remote="git@github.com:x/kb.git"):
        store = FakeStore()
        store.add_project(KNOWLEDGE_WORKSPACE, local_path=path, remote=remote)
        return store

    def test_bare_prints_the_registered_path(self):
        rc, out, err = self._run(self._store(), FakeGit(), [])
        self.assertEqual(rc, 0, err)
        self.assertEqual(out.strip(), "/kb")

    def test_check_passes_when_origin_matches(self):
        rc, out, err = self._run(
            self._store(), FakeGit(origin="git@github.com:x/kb.git"), ["--check"])
        self.assertEqual(rc, 0, err)
        self.assertIn("ok", out)
        self.assertIn("/kb", out)

    def test_check_fails_naming_origin_and_registered_remote_on_mismatch(self):
        rc, out, err = self._run(
            self._store(), FakeGit(origin="git@github.com:other/kb.git"), ["--check"])
        self.assertEqual(rc, 1)
        self.assertIn("git@github.com:other/kb.git", err)
        self.assertIn("git@github.com:x/kb.git", err)

    def test_check_fails_when_no_remote_is_registered(self):
        rc, out, err = self._run(self._store(remote=None), FakeGit(), ["--check"])
        self.assertEqual(rc, 1)
        self.assertIn("no remote registered", err)

    def test_fails_when_not_registered(self):
        rc, out, err = self._run(FakeStore(), FakeGit(), [])
        self.assertEqual(rc, 1)
        self.assertIn("no '%s' project registered" % KNOWLEDGE_WORKSPACE, err)
        self.assertIn("lc init", err)


if __name__ == "__main__":
    unittest.main()
