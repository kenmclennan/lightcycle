import unittest

from lightcycle.application.pool.no_op_gates import (
    NoOpFs, NoOpGit, NoOpSpinPort, NoOpStream, NoOpWorktrees,
)
from lightcycle.application.pool.reap_orphan_processes import OrphanProcess, OrphanReapResponse
from lightcycle.application.pool.sweep import SweepUseCase
from lightcycle.ports.workers import RegistryUnreadable
from tests.support.fake_orphan_reaper import RecordingOrphanReaper
from tests.support.fake_store import FakeStore
from tests.support.fake_workers import FakeWorkers


class _OrderedStore(FakeStore):
    def __init__(self, log):
        super().__init__()
        self._log = log

    def reclaim(self, step_id):
        self._log.append("reclaim")
        return super().reclaim(step_id)


class _Workers(FakeWorkers):
    def __init__(self, log, unreadable=False):
        super().__init__()
        self._log = log
        self._unreadable = unreadable

    def prune_workers(self, keep_dead=None):
        self._log.append("prune")
        return 0

    def workers_state(self):
        if self._unreadable:
            raise RegistryUnreadable("x")
        return super().workers_state()


def _sweep(store, workers, reaper):
    return SweepUseCase(
        store, workers, worktrees=NoOpWorktrees(), git=NoOpGit(), worker_log=NoOpFs(),
        spin_port=NoOpSpinPort(), spin_cap=3, stream=NoOpStream(), orphan_reaper=reaper,
    ).execute(100.0, 120, 1800)


class TestSweepOrphanReap(unittest.TestCase):
    def test_reaper_runs_after_reclaim_and_result_is_in_the_response(self):
        log = []
        store = _OrderedStore(log)
        item = store.create_item("item", "a description")
        step = store.create_step(item=item, role="agent")
        store.update_state(step, "in_progress")
        response = OrphanReapResponse(
            ended=[OrphanProcess(1, "/a")], unended=[OrphanProcess(2, "/b")],
            left=[OrphanProcess(3, "/c")])
        reaper = RecordingOrphanReaper(response, log)

        result = _sweep(store, _Workers(log), reaper)

        self.assertEqual(log, ["reclaim", "reap", "prune"])
        self.assertEqual(result.orphans_ended, response.ended)
        self.assertEqual(result.orphans_unended, response.unended)
        self.assertEqual(result.orphans_left, response.left)

    def test_reaper_is_skipped_when_the_registry_is_unreadable(self):
        log = []
        reaper = RecordingOrphanReaper(log=log)

        result = _sweep(FakeStore(), _Workers(log, unreadable=True), reaper)

        self.assertEqual(reaper.calls, 0)
        self.assertEqual(result.orphans_ended, [])
