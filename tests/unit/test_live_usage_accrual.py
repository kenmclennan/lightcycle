import json
import unittest

from lightcycle.application.pool.live_usage import LiveUsageAccrualUseCase
from tests.support.fake_fs import FakeFs
from tests.support.fake_store import FakeStore
from tests.support.fake_workers import FakeWorkers


class RecordingFakeFs(FakeFs):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.read_from_calls = []

    def read_from_bounded(self, path, offset, max_bytes):
        self.read_from_calls.append((path, offset))
        return super().read_from_bounded(path, offset, max_bytes)


class RecordingFakeStore(FakeStore):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.record_usage_calls = []
        self.record_attribution_calls = []

    def record_usage(self, tid, input_tokens, output_tokens, cache_read_tokens,
                      cache_creation_tokens, cost_usd, cost_basis, thinking_tokens):
        self.record_usage_calls.append(
            (tid, input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens,
             cost_usd, cost_basis, thinking_tokens)
        )

    def record_attribution(self, tid, turn_count, tool_usage):
        self.record_attribution_calls.append((tid, turn_count, tool_usage))


class FakeConfig:
    def usage_pricing(self):
        return {"sonnet": {"input": 2.0, "output": 10.0, "cache_write": 2.5, "cache_read": 0.2}}


def _assistant(message_id, tool_use=None, usage=None):
    content = []
    if tool_use:
        content.append({"type": "tool_use", "id": tool_use[0], "name": tool_use[1]})
    message = {"id": message_id, "content": content}
    if usage is not None:
        message["usage"] = usage
    return json.dumps({"type": "assistant", "message": message})


def _user(tool_use_id, content):
    return json.dumps({
        "type": "user",
        "message": {"content": [
            {"type": "tool_result", "tool_use_id": tool_use_id, "content": content},
        ]},
    })


class TestLiveUsageAccrualUseCase(unittest.TestCase):
    def _worker(self, step):
        return {"spawnid": "sp-1", "role": "agent", "pid": 1, "step": step, "log": "/l/1.log",
                "started": 0}

    def test_a_live_worker_with_a_step_gets_its_delta_posted(self):
        store = RecordingFakeStore()
        tid = store.create_step("build: t", step="build", role="agent")
        store.set_model(tid, "sonnet")
        lines = [
            _assistant("msg-1", tool_use=("tu-1", "Bash"),
                       usage={"input_tokens": 100, "output_tokens": 50,
                              "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}),
            _user("tu-1", "hello"),
        ]
        content = ("\n".join(lines) + "\n").encode()
        fs = FakeFs(files={"/l/1.log": content})
        workers = FakeWorkers(workers=[self._worker(tid)], alive_pids={1})
        LiveUsageAccrualUseCase(store, fs, workers, FakeConfig()).execute(now=100)

        self.assertEqual(len(store.record_usage_calls), 1)
        recorded = store.record_usage_calls[0]
        self.assertEqual(recorded[:5], (tid, 100, 50, 0, 0))
        self.assertEqual(recorded[6], "derived")
        self.assertIsNone(recorded[7])

        self.assertEqual(len(store.record_attribution_calls), 1)
        recorded_tid, turn_count, tool_usage = store.record_attribution_calls[0]
        self.assertEqual(recorded_tid, tid)
        self.assertEqual(turn_count, 1)
        self.assertEqual(tool_usage["Bash"].calls, 1)
        self.assertEqual(tool_usage["Bash"].bytes, len(b"hello"))

        resume = store.usage_accrual_state("sp-1")
        self.assertEqual(resume["offset"], len(content))
        self.assertEqual(resume["message_ids"], ["msg-1"])
        self.assertEqual(resume["pending_tool_use"], {})
        self.assertEqual(resume["posted_turn_count"], 1)
        self.assertEqual(resume["posted_input_tokens"], 100)

    def test_a_second_tick_against_a_longer_log_posts_only_the_new_delta(self):
        store = RecordingFakeStore()
        tid = store.create_step("build: t", step="build", role="agent")
        store.set_model(tid, "sonnet")
        first_lines = [
            _assistant("msg-1", tool_use=("tu-1", "Bash"),
                       usage={"input_tokens": 100, "output_tokens": 50,
                              "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}),
            _user("tu-1", "hello"),
        ]
        first_content = ("\n".join(first_lines) + "\n").encode()
        fs = RecordingFakeFs(files={"/l/1.log": first_content})
        workers = FakeWorkers(workers=[self._worker(tid)], alive_pids={1})
        use_case = LiveUsageAccrualUseCase(store, fs, workers, FakeConfig())
        use_case.execute(now=100)
        first_offset = store.usage_accrual_state("sp-1")["offset"]
        self.assertEqual(fs.read_from_calls, [("/l/1.log", 0)])

        second_lines = [
            _assistant("msg-2", tool_use=("tu-2", "Read"),
                       usage={"input_tokens": 5, "output_tokens": 1,
                              "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}),
            _user("tu-2", "world"),
        ]
        fs._files["/l/1.log"] = first_content + ("\n".join(second_lines) + "\n").encode()
        use_case.execute(now=101)

        self.assertEqual(fs.read_from_calls[-1], ("/l/1.log", first_offset))
        self.assertEqual(len(store.record_usage_calls), 2)
        second = store.record_usage_calls[1]
        self.assertEqual(second[:5], (tid, 5, 1, 0, 0))

    def test_a_tick_against_an_unchanged_log_makes_no_store_calls(self):
        store = RecordingFakeStore()
        tid = store.create_step("build: t", step="build", role="agent")
        store.set_model(tid, "sonnet")
        lines = [
            _assistant("msg-1", tool_use=("tu-1", "Bash"),
                       usage={"input_tokens": 100, "output_tokens": 50,
                              "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}),
            _user("tu-1", "hello"),
        ]
        content = ("\n".join(lines) + "\n").encode()
        fs = FakeFs(files={"/l/1.log": content})
        workers = FakeWorkers(workers=[self._worker(tid)], alive_pids={1})
        use_case = LiveUsageAccrualUseCase(store, fs, workers, FakeConfig())
        use_case.execute(now=100)
        self.assertEqual(len(store.record_usage_calls), 1)

        use_case.execute(now=101)
        self.assertEqual(len(store.record_usage_calls), 1)
        self.assertEqual(len(store.record_attribution_calls), 1)

    def test_a_chunk_ending_mid_line_does_not_advance_offset_or_double_count(self):
        store = RecordingFakeStore()
        tid = store.create_step("build: t", step="build", role="agent")
        store.set_model(tid, "sonnet")
        partial = '{"type":"assistant","message":{"id":"msg-1"'
        fs = FakeFs(files={"/l/1.log": partial.encode()})
        workers = FakeWorkers(workers=[self._worker(tid)], alive_pids={1})
        use_case = LiveUsageAccrualUseCase(store, fs, workers, FakeConfig())
        use_case.execute(now=100)

        self.assertEqual(store.record_attribution_calls, [])
        self.assertIsNone(store.usage_accrual_state("sp-1"))

        full_line = _assistant("msg-1") + "\n"
        fs._files["/l/1.log"] = full_line.encode()
        use_case.execute(now=101)

        self.assertEqual(len(store.record_attribution_calls), 1)
        recorded_tid, turn_count, _ = store.record_attribution_calls[0]
        self.assertEqual(turn_count, 1)
        self.assertEqual(store.usage_accrual_state("sp-1")["offset"], len(full_line.encode()))


if __name__ == "__main__":
    unittest.main()
