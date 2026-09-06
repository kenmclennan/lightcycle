import json
import unittest

from lightcycle.application.pool.backfill_usage import BackfillUsageUseCase
from tests.support.fake_fs import FakeFs
from tests.support.fake_store import FakeStore


def _claim_result_log(step_id):
    lines = [
        json.dumps({
            "type": "assistant",
            "message": {"id": "msg-1", "content": [
                {"type": "tool_use", "id": "tu-1", "name": "Bash",
                 "input": {"command": "lc claim agent"}},
            ]},
        }),
        json.dumps({
            "type": "user",
            "message": {"content": [
                {"type": "tool_result", "tool_use_id": "tu-1", "content": json.dumps({"id": step_id})},
            ]},
        }),
    ]
    return "\n".join(lines).encode()


def _no_claim_log():
    return b'{"type":"assistant","message":{"id":"msg-1","content":[]}}'


class FakeWorkers:
    def __init__(self, workers=None):
        self._workers = workers or []

    def workers_state(self):
        return self._workers


class FakeConfig:
    def __init__(self, root="/home"):
        self._root = root

    def data_root(self):
        return self._root


class TestBackfillUsageUseCase(unittest.TestCase):
    def test_first_run_records_matched_and_unmatched_logs(self):
        store = FakeStore()
        tid = store.create_step("build: t", step="build", role="agent")
        tid2 = store.create_step("write-code: t", step="write-code", role="agent")
        fs = FakeFs(files={
            "/home/logs/worker-a.log": _claim_result_log(tid),
            "/home/logs/worker-b.log": _claim_result_log(tid2),
            "/home/logs/worker-c.log": _no_claim_log(),
        })
        workers = FakeWorkers()

        resp = BackfillUsageUseCase(store, fs, workers, FakeConfig()).execute()

        self.assertEqual(resp.total, 3)
        self.assertEqual(resp.matched, 2)
        self.assertEqual(resp.unmatched, 1)
        self.assertEqual(resp.skipped_pending, 0)
        self.assertEqual(resp.orphaned, 0)
        self.assertEqual(resp.stored, 2)
        self.assertEqual(
            store.usage_backfilled_logs(),
            {"/home/logs/worker-a.log", "/home/logs/worker-b.log", "/home/logs/worker-c.log"},
        )

    def test_matched_log_whose_step_no_longer_exists_is_reported_as_orphaned_not_stored(self):
        store = FakeStore()
        fs = FakeFs(files={"/home/logs/worker-a.log": _claim_result_log("gone-step")})
        workers = FakeWorkers()

        resp = BackfillUsageUseCase(store, fs, workers, FakeConfig()).execute()

        self.assertEqual(resp.matched, 1)
        self.assertEqual(resp.orphaned, 1)
        self.assertEqual(resp.stored, 0)
        self.assertIn("/home/logs/worker-a.log", store.usage_backfilled_logs())

    def test_second_run_is_a_no_op(self):
        store = FakeStore()
        tid = store.create_step("build: t", step="build", role="agent")
        tid2 = store.create_step("write-code: t", step="write-code", role="agent")
        fs = FakeFs(files={
            "/home/logs/worker-a.log": _claim_result_log(tid),
            "/home/logs/worker-b.log": _claim_result_log(tid2),
            "/home/logs/worker-c.log": _no_claim_log(),
        })
        workers = FakeWorkers()
        BackfillUsageUseCase(store, fs, workers, FakeConfig()).execute()

        resp = BackfillUsageUseCase(store, fs, workers, FakeConfig()).execute()

        self.assertEqual(resp.matched, 0)
        self.assertEqual(resp.total, 0)

    def test_log_still_pending_live_capture_is_skipped_not_matched_or_unmatched(self):
        store = FakeStore()
        tid = store.create_step("build: t", step="build", role="agent")
        fs = FakeFs(files={"/home/logs/worker-a.log": _claim_result_log(tid)})
        workers = FakeWorkers(workers=[
            {"spawnid": "sp-1", "log": "/home/logs/worker-a.log", "checked": False},
        ])

        resp = BackfillUsageUseCase(store, fs, workers, FakeConfig()).execute()

        self.assertEqual(resp.total, 1)
        self.assertEqual(resp.matched, 0)
        self.assertEqual(resp.unmatched, 0)
        self.assertEqual(resp.skipped_pending, 1)
        self.assertEqual(store.usage_backfilled_logs(), set())


if __name__ == "__main__":
    unittest.main()
