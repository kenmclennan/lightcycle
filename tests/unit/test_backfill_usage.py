import json
import unittest

from lightcycle.adapters.claude_stream import ClaudeStreamAdapter
from lightcycle.application.pool.backfill_usage import BackfillUsageUseCase
from lightcycle.application.pool.breaker_gate import BreakerGateUseCase
from lightcycle.domain.money import Cost
from lightcycle.domain.pool import ModelRates, ToolUsage
from lightcycle.domain.pool.worker import Worker
from lightcycle.ports.breaker import BreakerPort
from tests.support.fake_fs import FakeFs
from tests.support.fake_store import FakeStore
from tests.support.step_factory import create_owned_step


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
        return [Worker.from_state(d) for d in self._workers]


class FakeConfig:
    def __init__(self, root="/home"):
        self._root = root

    def data_root(self):
        return self._root

    def usage_pricing(self):
        return {"sonnet": ModelRates(input=2.0, output=10.0, cache_write=2.5, cache_read=0.2)}

    def max_boot_seconds(self):
        return 120

    def stall_seconds(self):
        return 1800

    def probe_cooldown_seconds(self):
        return 1800

    def spin_cap(self):
        return 2


class ReapAndBackfillWorkers:
    def __init__(self, workers):
        self._workers = workers

    def workers_state(self):
        return [Worker.from_state(d) for d in self._workers]

    def pid_alive(self, pid, started=None):
        return False

    def mark_checked(self, spawnid):
        for w in self._workers:
            if w.get("spawnid") == spawnid:
                w["checked"] = True


class FakeBreakerPort(BreakerPort):
    def __init__(self):
        self._state = {}

    def load(self):
        return dict(self._state)

    def save(self, state):
        self._state = dict(state)


class TestBackfillUsageUseCase(unittest.TestCase):
    def test_first_run_records_matched_and_unmatched_logs(self):
        store = FakeStore()
        tid = create_owned_step(store, "build: t", step="build", role="agent")
        tid2 = create_owned_step(store, "write-code: t", step="write-code", role="agent")
        fs = FakeFs(files={
            "/home/logs/worker-a.log": _claim_result_log(tid),
            "/home/logs/worker-b.log": _claim_result_log(tid2),
            "/home/logs/worker-c.log": _no_claim_log(),
        })
        workers = FakeWorkers()

        resp = BackfillUsageUseCase(store, fs, workers, FakeConfig(), fs, stream=ClaudeStreamAdapter()).execute()

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

    def test_fs_and_worker_log_are_used_as_two_distinct_ports_not_one_object_twice(self):
        store = FakeStore()
        tid = create_owned_step(store, "build: t", step="build", role="agent")
        files = {"/home/logs/worker-a.log": _claim_result_log(tid)}

        class _ExistsOnlyFs:
            def exists(self, path):
                return path in files

        class _WorkerLogOnly:
            def iter_lines(self, path):
                content = files.get(path)
                if content is None:
                    return
                for line in content.decode("utf-8", errors="replace").splitlines(keepends=True):
                    yield line

            def list_worker_log_files(self, root):
                prefix = root + "/logs/"
                return sorted(
                    f for f in files
                    if f.startswith(prefix) and f.rsplit("/", 1)[-1].startswith("worker-")
                    and f.endswith(".log")
                )

        workers = FakeWorkers()

        resp = BackfillUsageUseCase(
            store, _ExistsOnlyFs(), workers, FakeConfig(), _WorkerLogOnly(), stream=ClaudeStreamAdapter()).execute()

        self.assertEqual(resp.total, 1)
        self.assertEqual(resp.matched, 1)
        self.assertEqual(resp.stored, 1)

    def test_matched_log_whose_step_no_longer_exists_is_reported_as_orphaned_not_stored(self):
        store = FakeStore()
        fs = FakeFs(files={"/home/logs/worker-a.log": _claim_result_log("gone-step")})
        workers = FakeWorkers()

        resp = BackfillUsageUseCase(store, fs, workers, FakeConfig(), fs, stream=ClaudeStreamAdapter()).execute()

        self.assertEqual(resp.matched, 1)
        self.assertEqual(resp.orphaned, 1)
        self.assertEqual(resp.stored, 0)
        self.assertIn("/home/logs/worker-a.log", store.usage_backfilled_logs())

    def test_second_run_is_a_no_op(self):
        store = FakeStore()
        tid = create_owned_step(store, "build: t", step="build", role="agent")
        tid2 = create_owned_step(store, "write-code: t", step="write-code", role="agent")
        fs = FakeFs(files={
            "/home/logs/worker-a.log": _claim_result_log(tid),
            "/home/logs/worker-b.log": _claim_result_log(tid2),
            "/home/logs/worker-c.log": _no_claim_log(),
        })
        workers = FakeWorkers()
        BackfillUsageUseCase(store, fs, workers, FakeConfig(), fs, stream=ClaudeStreamAdapter()).execute()

        resp = BackfillUsageUseCase(store, fs, workers, FakeConfig(), fs, stream=ClaudeStreamAdapter()).execute()

        self.assertEqual(resp.matched, 0)
        self.assertEqual(resp.total, 0)

    def test_log_still_pending_live_capture_is_skipped_not_matched_or_unmatched(self):
        store = FakeStore()
        tid = create_owned_step(store, "build: t", step="build", role="agent")
        fs = FakeFs(files={"/home/logs/worker-a.log": _claim_result_log(tid)})
        workers = FakeWorkers(workers=[
            {"spawnid": "sp-1", "log": "/home/logs/worker-a.log", "checked": False},
        ])

        resp = BackfillUsageUseCase(store, fs, workers, FakeConfig(), fs, stream=ClaudeStreamAdapter()).execute()

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
        tid = create_owned_step(store, "build: t", step="build", role="agent")
        store.set_model(tid, "sonnet")
        log_file = "/home/logs/worker-a.log"
        fs = FakeFs(files={log_file: _assistant_usage_log(1_000_000)})
        store._backfill_log[log_file] = (tid, None)
        workers = FakeWorkers()

        resp = BackfillUsageUseCase(store, fs, workers, FakeConfig(), fs, stream=ClaudeStreamAdapter()).execute()

        self.assertEqual(resp.reclassified, 1)
        self.assertEqual(resp.recovered, 1)
        t = store.get_node(tid)
        self.assertEqual(t.usage_input_tokens, 1_000_000)
        self.assertEqual(t.usage_cost_usd, Cost.from_usd(2.0))
        self.assertEqual(t.usage_cost_basis, "derived")

    def test_an_unclassified_row_that_turns_out_to_have_a_result_line_only_flips_classification(self):
        store = FakeStore()
        tid = create_owned_step(store, "build: t", step="build", role="agent")
        log_file = "/home/logs/worker-a.log"
        fs = FakeFs(files={log_file: _result_log()})
        store._backfill_log[log_file] = (tid, None)
        workers = FakeWorkers()

        resp = BackfillUsageUseCase(store, fs, workers, FakeConfig(), fs, stream=ClaudeStreamAdapter()).execute()

        self.assertEqual(resp.reclassified, 1)
        self.assertEqual(resp.recovered, 0)
        t = store.get_node(tid)
        self.assertEqual(t.usage_input_tokens, 0)
        self.assertEqual(t.usage_cost_usd, Cost())

    def test_an_empty_unclassified_set_leaves_the_main_loop_behavior_unchanged(self):
        store = FakeStore()
        tid = create_owned_step(store, "build: t", step="build", role="agent")
        fs = FakeFs(files={"/home/logs/worker-a.log": _claim_result_log(tid)})
        workers = FakeWorkers()

        resp = BackfillUsageUseCase(store, fs, workers, FakeConfig(), fs, stream=ClaudeStreamAdapter()).execute()

        self.assertEqual(resp.reclassified, 0)
        self.assertEqual(resp.recovered, 0)
        self.assertEqual(resp.total, 1)
        self.assertEqual(resp.matched, 1)
        self.assertEqual(resp.stored, 1)


def _claim_result_log_with_usage(step_id, input_tokens, cost):
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
        json.dumps({
            "type": "result",
            "modelUsage": {
                "claude-sonnet-5": {"inputTokens": input_tokens, "costUSD": cost, "costBasis": "list"},
            },
        }),
    ]
    return "\n".join(lines).encode()


def _bash_tool_usage(step_id):
    return {"Bash": ToolUsage(calls=1, bytes=len(json.dumps({"id": step_id}).encode()))}


class TestBackfillUsageDoesNotDoubleALiveCapturedLog(unittest.TestCase):
    def test_a_log_reaped_live_then_backfilled_is_ingested_once(self):
        store = FakeStore()
        tid = create_owned_step(store, "build: t", step="build", role="agent")
        log_file = "/home/logs/worker-a.log"
        fs = FakeFs(files={log_file: _claim_result_log_with_usage(tid, 68, 0.5)})
        workers_state = [{"spawnid": "sp-1", "pid": 1, "step": tid, "log": log_file, "started": 0}]
        workers = ReapAndBackfillWorkers(workers_state)
        config = FakeConfig()

        BreakerGateUseCase(workers, fs, FakeBreakerPort(), config, store=store, stream=ClaudeStreamAdapter()).execute(now=100)

        after_reap = store.get_node(tid)
        single_ingest_usage = after_reap.usage_input_tokens
        single_ingest_turns = after_reap.turn_count
        single_ingest_tools = store.tool_usage_for(tid)
        self.assertIn(log_file, store.usage_backfilled_logs())

        resp = BackfillUsageUseCase(store, fs, workers, config, fs, stream=ClaudeStreamAdapter()).execute()

        self.assertEqual(resp.total, 0)
        self.assertEqual(store.get_node(tid).usage_input_tokens, single_ingest_usage)
        self.assertEqual(store.get_node(tid).turn_count, single_ingest_turns)
        self.assertEqual(store.tool_usage_for(tid), single_ingest_tools)


class RecordingFakeStore(FakeStore):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.overwrite_calls = []

    def overwrite_usage_and_attribution(self, step_id, usage_totals, turn_count, tool_usage_totals):
        self.overwrite_calls.append((step_id, usage_totals, turn_count, tool_usage_totals))
        super().overwrite_usage_and_attribution(step_id, usage_totals, turn_count, tool_usage_totals)


class TestBackfillUsageRepair(unittest.TestCase):
    def test_repair_leaves_an_already_healthy_step_untouched(self):
        store = RecordingFakeStore()
        tid = create_owned_step(store, "build: t", step="build", role="agent")
        log_a, log_b = "/home/logs/worker-a.log", "/home/logs/worker-b.log"
        fs = FakeFs(files={
            log_a: _claim_result_log_with_usage(tid, 10, 0.1),
            log_b: _claim_result_log_with_usage(tid, 20, 0.2),
        })
        workers = FakeWorkers()
        BackfillUsageUseCase(store, fs, workers, FakeConfig(), fs, stream=ClaudeStreamAdapter()).execute()

        resp = BackfillUsageUseCase(store, fs, workers, FakeConfig(), fs, stream=ClaudeStreamAdapter()).execute(repair=True)

        self.assertEqual(resp.repair_examined, 1)
        self.assertEqual(resp.repair_corrected, 0)
        self.assertEqual(store.overwrite_calls, [])

    def test_repair_corrects_a_step_whose_stored_totals_are_exactly_doubled(self):
        store = RecordingFakeStore()
        tid = create_owned_step(store, "build: t", step="build", role="agent")
        log_file = "/home/logs/worker-a.log"
        fs = FakeFs(files={log_file: _claim_result_log_with_usage(tid, 68, 0.5)})
        store.record_usage(tid, 68, 0, 0, 0, 0.5, "list", None)
        store.record_usage(tid, 68, 0, 0, 0, 0.5, "list", None)
        store.record_attribution(tid, 1, _bash_tool_usage(tid))
        store.record_attribution(tid, 1, _bash_tool_usage(tid))
        store._backfill_log[log_file] = (tid, True)
        workers = FakeWorkers()

        resp = BackfillUsageUseCase(store, fs, workers, FakeConfig(), fs, stream=ClaudeStreamAdapter()).execute(repair=True)

        self.assertEqual(resp.repair_examined, 1)
        self.assertEqual(resp.repair_corrected, 1)
        t = store.get_node(tid)
        self.assertEqual(t.usage_input_tokens, 68)
        self.assertEqual(t.usage_cost_usd, Cost.from_usd(0.5))
        self.assertEqual(t.turn_count, 1)
        self.assertEqual(store.tool_usage_for(tid), _bash_tool_usage(tid))

    def test_repair_skips_a_missing_ledgered_log_and_reports_it_without_crashing(self):
        store = RecordingFakeStore()
        tid = create_owned_step(store, "build: t", step="build", role="agent")
        present_log = "/home/logs/worker-a.log"
        missing_log = "/home/logs/worker-b.log"
        fs = FakeFs(files={present_log: _claim_result_log_with_usage(tid, 68, 0.5)})
        workers = FakeWorkers()
        BackfillUsageUseCase(store, fs, workers, FakeConfig(), fs, stream=ClaudeStreamAdapter()).execute()
        store._backfill_log[missing_log] = (tid, True)

        resp = BackfillUsageUseCase(store, fs, workers, FakeConfig(), fs, stream=ClaudeStreamAdapter()).execute(repair=True)

        self.assertEqual(resp.repair_examined, 1)
        self.assertEqual(resp.repair_missing_logs, 1)
        self.assertEqual(resp.repair_corrected, 0)
        t = store.get_node(tid)
        self.assertEqual(t.usage_input_tokens, 68)


class TestBackfillUsageTransitionWindowHazard(unittest.TestCase):
    def test_a_pre_fix_live_captured_log_with_no_ledger_row_still_doubles_but_repair_fixes_it(self):
        store = FakeStore()
        tid = create_owned_step(store, "build: t", step="build", role="agent")
        log_file = "/home/logs/worker-a.log"
        fs = FakeFs(files={log_file: _claim_result_log_with_usage(tid, 68, 0.5)})
        store.record_usage(tid, 68, 0, 0, 0, 0.5, "list", None)
        store.record_attribution(tid, 1, _bash_tool_usage(tid))
        workers = FakeWorkers()

        resp = BackfillUsageUseCase(store, fs, workers, FakeConfig(), fs, stream=ClaudeStreamAdapter()).execute()

        self.assertEqual(resp.stored, 1)
        self.assertEqual(store.get_node(tid).usage_input_tokens, 136)

        repair_resp = BackfillUsageUseCase(store, fs, workers, FakeConfig(), fs, stream=ClaudeStreamAdapter()).execute(repair=True)

        self.assertEqual(repair_resp.repair_corrected, 1)
        self.assertEqual(store.get_node(tid).usage_input_tokens, 68)


if __name__ == "__main__":
    unittest.main()
