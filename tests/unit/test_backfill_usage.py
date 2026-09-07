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

    def usage_pricing(self):
        return {"sonnet": {"input": 2.0, "output": 10.0, "cache_write": 2.5, "cache_read": 0.2}}


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
        self.assertEqual(resp.reclassified, 0)
        self.assertEqual(resp.recovered, 0)
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


def _assistant_usage_log(input_tokens):
    return json.dumps({
        "type": "assistant",
        "message": {
            "id": "msg-1", "content": [],
            "usage": {
                "input_tokens": input_tokens, "output_tokens": 0,
                "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0,
            },
        },
    }).encode()


def _result_log():
    return b'{"type":"result","modelUsage":{"claude-sonnet-5":{"inputTokens":5,"costUSD":0.1,"costBasis":"list"}}}'


class TestBackfillUsageReclassification(unittest.TestCase):
    def test_an_unclassified_row_that_still_has_no_result_line_recovers_and_prices_usage(self):
        store = FakeStore()
        tid = store.create_step("build: t", step="build", role="agent")
        store.set_model(tid, "sonnet")
        log_file = "/home/logs/worker-a.log"
        fs = FakeFs(files={log_file: _assistant_usage_log(1_000_000)})
        store._backfill_log[log_file] = (tid, None)
        workers = FakeWorkers()

        resp = BackfillUsageUseCase(store, fs, workers, FakeConfig()).execute()

        self.assertEqual(resp.reclassified, 1)
        self.assertEqual(resp.recovered, 1)
        t = store.get_node(tid)
        self.assertEqual(t.usage_input_tokens, 1_000_000)
        self.assertAlmostEqual(t.usage_cost_usd, 2.0)
        self.assertEqual(t.usage_cost_basis, "derived")

    def test_an_unclassified_row_that_turns_out_to_have_a_result_line_only_flips_classification(self):
        store = FakeStore()
        tid = store.create_step("build: t", step="build", role="agent")
        log_file = "/home/logs/worker-a.log"
        fs = FakeFs(files={log_file: _result_log()})
        store._backfill_log[log_file] = (tid, None)
        workers = FakeWorkers()

        resp = BackfillUsageUseCase(store, fs, workers, FakeConfig()).execute()

        self.assertEqual(resp.reclassified, 1)
        self.assertEqual(resp.recovered, 0)
        t = store.get_node(tid)
        self.assertEqual(t.usage_input_tokens, 0)
        self.assertEqual(t.usage_cost_usd, 0.0)

    def test_an_empty_unclassified_set_leaves_the_main_loop_behavior_unchanged(self):
        store = FakeStore()
        tid = store.create_step("build: t", step="build", role="agent")
        fs = FakeFs(files={"/home/logs/worker-a.log": _claim_result_log(tid)})
        workers = FakeWorkers()

        resp = BackfillUsageUseCase(store, fs, workers, FakeConfig()).execute()

        self.assertEqual(resp.reclassified, 0)
        self.assertEqual(resp.recovered, 0)
        self.assertEqual(resp.total, 1)
        self.assertEqual(resp.matched, 1)
        self.assertEqual(resp.stored, 1)


if __name__ == "__main__":
    unittest.main()
