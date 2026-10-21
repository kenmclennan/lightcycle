import unittest

from lightcycle.application.errors import UseCaseError
from lightcycle.application.work.remove_node import RemoveNodeInput, RemoveNodeUseCase
from lightcycle.domain.runs import RunState
from tests.support.fake_git import FakeGit
from tests.unit.test_close_item_teardown_guard import BRANCH, REPO, _world
from tests.unit.test_work_writes import FakeWorkersForRemove


class _Worktrees:
    def __init__(self, svc):
        self._svc = svc
        self.removed = []

    def has_worktree_history(self, item):
        return self._svc.has_worktree_history(item)

    def worktrees_of(self, item):
        return self._svc.worktrees_of(item)

    def unmerged_refusals(self, item, merged_prs=frozenset()):
        return self._svc.unmerged_refusals(item, merged_prs)

    def remove(self, item):
        self.removed.append(item)


def _remove(store, svc, git, item, force=False):
    return RemoveNodeUseCase(store, FakeWorkersForRemove(), _Worktrees(svc), git).execute(
        RemoveNodeInput(id=item, force=force)
    )


def _removed(git):
    return [c for c in git.calls if c[0] in ("remove_worktree", "delete_branch")]


class TestRemoveNodeUnmergedGuard(unittest.TestCase):
    def test_branch_with_commits_beyond_the_base_is_refused_naming_the_branch(self):
        git = FakeGit(branches={(REPO, BRANCH)}, ref="origin/main", beyond={(REPO, BRANCH): ["a1"]})
        store, svc, item, _ = _world(git)

        with self.assertRaises(UseCaseError) as ctx:
            _remove(store, svc, git, item)

        self.assertIn(BRANCH, str(ctx.exception))
        self.assertIn("--force", str(ctx.exception))
        self.assertEqual(_removed(git), [])
        self.assertEqual(store.get_node(item).id, item)

    def test_force_removes_an_unmerged_branch(self):
        git = FakeGit(branches={(REPO, BRANCH)}, ref="origin/main", beyond={(REPO, BRANCH): ["a1"]})
        store, svc, item, _ = _world(git)

        _remove(store, svc, git, item, force=True)

        with self.assertRaises(KeyError):
            store.get_node(item)

    def test_merged_run_is_removed_without_force(self):
        git = FakeGit(branches={(REPO, BRANCH)}, ref="origin/main", beyond={(REPO, BRANCH): ["a1"]})
        store, svc, item, _ = _world(git, run_state=RunState.MERGED)

        _remove(store, svc, git, item)

        with self.assertRaises(KeyError):
            store.get_node(item)

    def test_branch_with_nothing_beyond_the_base_is_removed_without_force(self):
        git = FakeGit(branches={(REPO, BRANCH)}, ref="origin/main")
        store, svc, item, _ = _world(git)

        _remove(store, svc, git, item)

        with self.assertRaises(KeyError):
            store.get_node(item)


if __name__ == "__main__":
    unittest.main()
