import contextlib
import io
import unittest

from lightcycle.application.flow.complete_step import CompleteStepUseCase
from lightcycle.application.flow.passes import PassBook
from lightcycle.application.work.close_item import (
    RELEASE_PENDING_LABEL, CloseItemInput, CloseItemUseCase,
)
from lightcycle.application.work.remove_node import RemoveNodeInput, RemoveNodeUseCase
from lightcycle.ports.git import GitReadError
from tests.support.fake_git import FakeGit
from tests.unit.test_close_item_teardown_guard import BRANCH, REPO, _world
from tests.unit.test_remove_node_unmerged_guard import _Worktrees
from tests.unit.test_work_writes import FakeWorkersForRemove


def _git(**kw):
    return FakeGit(branches={(REPO, BRANCH)}, ref="origin/main", **kw)


def _stderr():
    return contextlib.redirect_stderr(io.StringIO())


class _FailingRemove(_Worktrees):
    def remove(self, item):
        raise GitReadError("boom")


class TestWorktreeServiceRemove(unittest.TestCase):
    def test_remove_attempts_every_run_then_raises_once_with_the_joined_messages(self):
        git = _git(raises=("remove_worktree",))
        store, svc, item, _ = _world(git)
        pid = store.current_pass(item).id
        second = store.open_run(item, pid, "other")
        store.set_branch(second, "feat/second")

        with self.assertRaises(GitReadError) as ctx:
            svc.remove(item)

        self.assertEqual(len([c for c in git.calls if c[0] == "remove_worktree"]), 2)
        self.assertEqual(str(ctx.exception).count("remove_worktree failed"), 2)
        self.assertIn("; ", str(ctx.exception))

    def test_a_failed_remote_delete_is_logged_and_release_returns_normally(self):
        git = _git(remote_delete_fails=True)
        store, svc, item, _ = _world(git)
        err = io.StringIO()

        with contextlib.redirect_stderr(err):
            svc.remove(item)

        self.assertEqual(git.remote_deletes, [(REPO, BRANCH)])
        self.assertIn("warning: remote branch delete failed for %s: boom" % BRANCH, err.getvalue())

    def test_a_failed_local_step_skips_the_remote_delete(self):
        git = _git(raises=("delete_branch",))
        store, svc, item, _ = _world(git)

        with self.assertRaises(GitReadError):
            svc.remove(item)

        self.assertEqual(git.remote_deletes, [])


class TestPassBookReleaseRuns(unittest.TestCase):
    def test_a_failing_run_is_logged_and_the_rest_still_release(self):
        class FailsFirst(FakeGit):
            def remove_worktree(self, root, path):
                if not any(c[0] == "remove_worktree" for c in self.calls):
                    self.calls.append(("remove_worktree", root, path))
                    raise GitReadError("locked")
                super().remove_worktree(root, path)

        git = FailsFirst(branches={(REPO, BRANCH)}, ref="origin/main")
        store, svc, item, _ = _world(git)
        pid = store.current_pass(item).id
        second = store.open_run(item, pid, "other")
        store.set_branch(second, "feat/second")
        runs = store.runs_of(item)
        err = io.StringIO()

        with contextlib.redirect_stderr(err):
            released = PassBook(store, None).release_runs(runs, svc)

        self.assertFalse(released)
        self.assertEqual(len([c for c in git.calls if c[0] == "remove_worktree"]), 2)
        self.assertIn("release-pending marker kept: locked", err.getvalue())

    def test_all_runs_released_reports_true(self):
        git = _git()
        store, svc, item, _ = _world(git)

        self.assertTrue(PassBook(store, None).release_runs(store.runs_of(item), svc))


class TestCompleteStepKeepsMarkerOnFailedPassEndRelease(unittest.TestCase):
    def _release(self, git):
        store, svc, item, _ = _world(git)
        store.label_add(item, RELEASE_PENDING_LABEL)
        with _stderr():
            CompleteStepUseCase(store, None, svc)._release(item, store.runs_of(item), False)
        return store.labels_of(item)

    def test_failed_release_keeps_the_label(self):
        self.assertIn(RELEASE_PENDING_LABEL, self._release(_git(raises=("remove_worktree",))))

    def test_successful_release_clears_the_label(self):
        self.assertNotIn(RELEASE_PENDING_LABEL, self._release(_git()))


class TestCloseItemRelease(unittest.TestCase):
    def _close(self, git):
        store, svc, item, _ = _world(git)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            CloseItemUseCase(store, svc).execute(
                CloseItemInput(item=item, reason="done", disposition="completed")
            )
        return store.labels_of(item), err.getvalue()

    def test_failed_removal_keeps_the_marker_and_does_not_raise(self):
        labels, err = self._close(_git(raises=("remove_worktree",)))

        self.assertIn(RELEASE_PENDING_LABEL, labels)
        self.assertIn("release-pending marker kept", err)

    def test_successful_removal_clears_the_marker(self):
        labels, _ = self._close(_git())

        self.assertNotIn(RELEASE_PENDING_LABEL, labels)


class TestRemoveNodeFailedRelease(unittest.TestCase):
    def test_returns_worktree_removed_false_and_warns(self):
        git = _git()
        store, svc, item, _ = _world(git)
        err = io.StringIO()

        with contextlib.redirect_stderr(err):
            resp = RemoveNodeUseCase(
                store, FakeWorkersForRemove(), _FailingRemove(svc), git
            ).execute(RemoveNodeInput(id=item, force=True))

        self.assertFalse(resp.worktree_removed)
        self.assertIn("worktree of %s not removed: boom" % item, err.getvalue())
