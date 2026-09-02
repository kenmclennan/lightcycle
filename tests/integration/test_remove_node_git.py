import tempfile
import unittest

from lightcycle.adapters.gitio import GitAdapter
from lightcycle.application.errors import UseCaseError
from lightcycle.application.work import RemoveNodeInput, RemoveNodeUseCase
from tests.support.fake_store import FakeStore


class FakeWorkers:
    def workers_state(self):
        return []

    def pid_alive(self, pid, started=None):
        return False


class FakeWorktrees:
    def __init__(self, target):
        self._target = target
        self.removed = []

    def has_repo(self, item):
        return True

    def has_worktree_history(self, item):
        return True

    def target_repo(self, item):
        return self._target

    def worktree_path(self, item):
        return self._target

    def remove(self, item):
        self.removed.append(item)


class TestRemoveNodeAgainstUnreadableWorktree(unittest.TestCase):
    def test_refuses_to_delete_when_the_worktree_cannot_be_read(self):
        s = FakeStore()
        item = s.create_item("feature", "a description")
        not_a_repo = tempfile.mkdtemp()
        wt = FakeWorktrees(not_a_repo)

        with self.assertRaises(UseCaseError) as ctx:
            RemoveNodeUseCase(s, FakeWorkers(), wt, GitAdapter()).execute(
                RemoveNodeInput(id=item)
            )

        self.assertIn("could not verify worktree state", str(ctx.exception))
        self.assertEqual(wt.removed, [])
        self.assertEqual(s.get_node(item).id, item)


if __name__ == "__main__":
    unittest.main()
