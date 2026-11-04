import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from lightcycle.adapters.gitio import GitAdapter
from lightcycle.ports.git import (
    RESTACK_CONFLICT,
    RESTACK_LEASE_LOST,
    RESTACK_PUSHED,
    RestackStep,
)


def _git(root, *args):
    return subprocess.run(
        ["git", "-C", root, *args], capture_output=True, text=True, check=True
    ).stdout.strip()


def _commit(root, name, text, message):
    (Path(root) / name).write_text(text)
    _git(root, "add", name)
    _git(root, "commit", "-q", "-m", message)


class _Stack(unittest.TestCase):
    def setUp(self):
        base = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, base, True)
        self.remote = base + "/remote.git"
        self.clone = base + "/clone"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", self.remote], check=True)
        subprocess.run(["git", "clone", "-q", self.remote, self.clone], check=True,
                       capture_output=True)
        _git(self.clone, "config", "user.email", "t@t")
        _git(self.clone, "config", "user.name", "t")
        _commit(self.clone, "base.txt", "base\n", "base")
        _git(self.clone, "push", "-q", "origin", "main")
        for branch, name in (("parent", "p.txt"), ("child", "c.txt"), ("gchild", "g.txt")):
            _git(self.clone, "checkout", "-q", "-b", branch)
            _commit(self.clone, name, branch + "\n", branch)
            _git(self.clone, "push", "-q", "origin", branch)
        self.parent_old = _git(self.clone, "rev-parse", "origin/parent")
        self.child_old = _git(self.clone, "rev-parse", "origin/child")
        self.gchild_old = _git(self.clone, "rev-parse", "origin/gchild")
        self.adapter = GitAdapter()

    def _remote_tip(self, branch):
        return _git(self.remote, "rev-parse", "refs/heads/" + branch)

    def _rework_parent(self, name="p2.txt", text="p2\n"):
        _git(self.clone, "checkout", "-q", "parent")
        _commit(self.clone, name, text, "parent rework")
        _git(self.clone, "push", "-q", "origin", "parent")
        return _git(self.clone, "rev-parse", "origin/parent")

    def _steps(self, parent_new, gchild_lease=None):
        return [
            RestackStep("child", self.child_old, self.parent_old, "origin/parent", None),
            RestackStep("gchild", gchild_lease or self.gchild_old, self.child_old, "child", None),
        ]


class TestRestackAgainstARealRemote(_Stack):
    def test_a_chain_is_rebased_onto_the_new_parent_head_and_pushed_together(self):
        parent_new = self._rework_parent()

        outcome = self.adapter.restack(self.clone, self._steps(parent_new))

        self.assertEqual(outcome.kind, RESTACK_PUSHED)
        self.assertEqual(self._remote_tip("child"), outcome.tips["child"])
        self.assertEqual(self._remote_tip("gchild"), outcome.tips["gchild"])
        self.assertEqual(_git(self.remote, "merge-base", "child", "parent"), parent_new)
        self.assertEqual(_git(self.remote, "merge-base", "gchild", "child"), outcome.tips["child"])
        self.assertEqual(_git(self.remote, "log", "--format=%s", "parent..gchild"), "gchild\nchild")

    def test_the_scratch_worktree_is_removed(self):
        parent_new = self._rework_parent()

        self.adapter.restack(self.clone, self._steps(parent_new))

        self.assertNotIn("lc-restack", _git(self.clone, "worktree", "list"))

    def test_a_stale_lease_names_the_branch_and_no_branch_moves(self):
        parent_new = self._rework_parent()
        _git(self.clone, "checkout", "-q", "gchild")
        _commit(self.clone, "other.txt", "x\n", "someone else")
        _git(self.clone, "push", "-q", "origin", "gchild")
        moved = self._remote_tip("gchild")

        outcome = self.adapter.restack(self.clone, self._steps(parent_new))

        self.assertEqual(outcome.kind, RESTACK_LEASE_LOST)
        self.assertEqual(outcome.branch, "gchild")
        self.assertEqual(self._remote_tip("child"), self.child_old)
        self.assertEqual(self._remote_tip("gchild"), moved)

    def test_a_conflict_names_the_files_and_pushes_nothing(self):
        self._rework_parent(name="c.txt", text="parent claims c\n")

        outcome = self.adapter.restack(self.clone, self._steps(None))

        self.assertEqual(outcome.kind, RESTACK_CONFLICT)
        self.assertEqual(outcome.branch, "child")
        self.assertEqual(outcome.files, ("c.txt",))
        self.assertEqual(self._remote_tip("child"), self.child_old)
        self.assertEqual(self._remote_tip("gchild"), self.gchild_old)

    def test_a_checked_out_worktree_is_reset_to_the_pushed_tip(self):
        parent_new = self._rework_parent()
        worktree = tempfile.mkdtemp() + "/wt"
        self.addCleanup(shutil.rmtree, worktree, True)
        _git(self.clone, "worktree", "add", "-q", worktree, "child")
        steps = self._steps(parent_new)
        steps[0] = RestackStep("child", self.child_old, self.parent_old, "origin/parent", worktree)

        outcome = self.adapter.restack(self.clone, steps)

        self.assertEqual(_git(worktree, "rev-parse", "HEAD"), outcome.tips["child"])

    def test_merge_base_answers_the_common_ancestor(self):
        self.assertEqual(
            self.adapter.merge_base(self.clone, "origin/child", "origin/parent"),
            self.parent_old)


class TestRetargetOntoASquashedDefaultBranch(_Stack):
    def test_the_child_keeps_only_its_own_commits_after_the_parent_is_squashed(self):
        _git(self.clone, "checkout", "-q", "main")
        _git(self.clone, "merge", "--squash", "origin/parent")
        _git(self.clone, "commit", "-q", "-m", "squash parent")
        _git(self.clone, "push", "-q", "origin", "main")
        steps = [RestackStep("child", self.child_old, self.parent_old, "origin/main", None)]

        outcome = self.adapter.restack(self.clone, steps)

        self.assertEqual(outcome.kind, RESTACK_PUSHED)
        self.assertEqual(_git(self.remote, "log", "--format=%s", "main..child"), "child")
