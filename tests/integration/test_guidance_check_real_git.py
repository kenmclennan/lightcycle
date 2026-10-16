import io
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import lightcycle.cli as cli_mod
from lightcycle.adapters.fsio import FsAdapter
from lightcycle.adapters.gitio import GitAdapter
from lightcycle.container import Container
from tests.unit.test_guidance_conventions import entry


def _git(root, *args):
    return subprocess.run(["git", "-C", root, *args], capture_output=True, text=True, check=True)


def _commit(root, message):
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", message)


class TestGuidanceCheckRealGit(unittest.TestCase):
    def setUp(self):
        self.repo = tempfile.mkdtemp()
        _git(self.repo, "init", "-q", "-b", "main")
        _git(self.repo, "config", "user.email", "t@t")
        _git(self.repo, "config", "user.name", "t")
        (Path(self.repo) / "kotlin.md").write_text("---\ntitle: k\n---\n")
        _commit(self.repo, "base")
        _git(self.repo, "branch", "base")
        _git(self.repo, "checkout", "-q", "-b", "work")
        self._orig = cli_mod._container
        self.addCleanup(lambda: cli_mod.set_container(self._orig))

    def _check(self):
        cli_mod.set_container(Container(
            config=object(), git=GitAdapter(), store=object(), spawner=object(),
            workers=object(), fs=FsAdapter(object()), github=object(), lock=object(), breaker=object(),
        ))
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = cli_mod.cmd_guidance_check(
                ["--dir", self.repo, "--mode", "draft", "--base", "base"]
            )
        return rc, out.getvalue(), err.getvalue()

    def test_uncommitted_edit_to_a_committed_entry_fails_naming_the_file(self):
        (Path(self.repo) / "a.md").write_text(entry())
        _commit(self.repo, "add a")
        (Path(self.repo) / "a.md").write_text(entry(purpose="edited"))

        rc, out, _ = self._check()

        self.assertEqual(rc, 1)
        self.assertIn("a.md", out)
        self.assertIn("commit", out)
        self.assertNotIn("clean", out)

    def test_staged_new_entry_fails_naming_the_file(self):
        (Path(self.repo) / "b.md").write_text(entry())
        _git(self.repo, "add", "b.md")

        rc, out, _ = self._check()

        self.assertEqual(rc, 1)
        self.assertIn("b.md", out)

    def test_untracked_new_entry_fails_naming_the_file(self):
        (Path(self.repo) / "c.md").write_text(entry())

        rc, out, _ = self._check()

        self.assertEqual(rc, 1)
        self.assertIn("c.md", out)

    def test_nothing_changed_against_the_base_does_not_say_clean(self):
        rc, out, _ = self._check()

        self.assertEqual(rc, 0)
        self.assertNotIn("clean", out)
        self.assertIn("no guidance files changed between base and HEAD", out)

    def test_committed_change_and_clean_tree_is_unchanged(self):
        (Path(self.repo) / "a.md").write_text(entry())
        _commit(self.repo, "add a")

        rc, out, _ = self._check()

        self.assertEqual(rc, 0)
        self.assertEqual(out.strip(), "1 changed file(s) clean (draft mode)")

    def test_uncommitted_non_markdown_file_does_not_fail(self):
        (Path(self.repo) / "notes.txt").write_text("x")

        rc, _, _ = self._check()

        self.assertEqual(rc, 0)
