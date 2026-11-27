import unittest

from lightcycle.application.services.orphaned_worktrees import (
    ORPHAN_RECHECK_SECONDS, OrphanedWorktree, OrphanedWorktrees,
)
from tests.support.fake_fs import FakeFs
from tests.support.fake_machine import FakeMachine
from tests.support.fake_store import FakeStore


class _Worktrees:
    def __init__(self, paths):
        self._paths = paths

    def worktree_path(self, node):
        return self._paths[node.item]


def _store_with_claim():
    store = FakeStore()
    store.add_project("acme", local_path="/repo")
    item = store.create_item("item", "a description")
    step = store.create_step(item=item, role="agent")
    store.update_state(step, "in_progress")
    return store, item


class TestOrphanedWorktreesScan(unittest.TestCase):
    def test_scan_reports_existing_unclaimed_and_deleted_worktrees(self):
        store, item = _store_with_claim()
        claimed = "/repo/.worktrees/%s-code" % item
        fs = FakeFs(dirs={"/repo/.worktrees": ["%s-code" % item, "idle"]})
        machine = FakeMachine(cwd_pids={
            claimed: [1], "/repo/.worktrees/idle": [2], "/repo/.worktrees/gone": [3, 4],
        })
        sleeps = []

        found = OrphanedWorktrees(
            store, fs, machine, _Worktrees({item: claimed}), sleeps.append).scan()

        self.assertEqual(found, [
            OrphanedWorktree("/repo/.worktrees/idle", True, [2]),
            OrphanedWorktree("/repo/.worktrees/gone", False, [3, 4]),
        ])
        self.assertEqual(sleeps, [ORPHAN_RECHECK_SECONDS])

    def test_claim_appearing_during_the_recheck_drops_the_worktree(self):
        store, item = _store_with_claim()
        path = "/repo/.worktrees/%s-code" % item
        fs = FakeFs(dirs={"/repo/.worktrees": ["%s-code" % item]})
        machine = FakeMachine(cwd_pids={path: [9]})
        claimed_steps = store.claimed_steps
        calls = []

        def claimed():
            calls.append(1)
            return [] if len(calls) == 1 else claimed_steps()

        store.claimed_steps = claimed

        found = OrphanedWorktrees(
            store, fs, machine, _Worktrees({item: path}), lambda s: None).scan()

        self.assertEqual(found, [])
        self.assertEqual(len(calls), 2)

    def test_scan_with_nothing_found_does_not_wait(self):
        store = FakeStore()
        store.add_project("acme", local_path="/repo")
        sleeps = []

        found = OrphanedWorktrees(
            store, FakeFs(dirs={"/repo/.worktrees": []}), FakeMachine(), _Worktrees({}),
            sleeps.append).scan()

        self.assertEqual((found, sleeps), ([], []))
