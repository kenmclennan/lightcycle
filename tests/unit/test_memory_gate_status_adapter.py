import glob
import io
import os
import tempfile
import unittest
from contextlib import redirect_stderr
from unittest.mock import patch

from lightcycle.adapters.memory_gate_status import MemoryGateStatusAdapter


class FakeConfig:
    def __init__(self, root):
        self._root = root

    def engine_root(self):
        return self._root

    def data_root(self):
        return self._root

    def prompts_root(self):
        return self._root


class TestMemoryGateStatusAdapter(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.status = MemoryGateStatusAdapter(FakeConfig(self.root))

    def test_load_with_no_state_file_is_empty(self):
        self.assertEqual(self.status.load(), {})

    def test_save_then_load_round_trips(self):
        self.status.save({"cap": 0, "pool_share": 0.5})
        self.assertEqual(
            self.status.load(), {"cap": 0, "pool_share": 0.5}
        )

    def test_state_survives_a_new_adapter_instance(self):
        self.status.save({"cap": 0, "pool_share": 0.5})
        reloaded = MemoryGateStatusAdapter(FakeConfig(self.root))
        self.assertEqual(
            reloaded.load(), {"cap": 0, "pool_share": 0.5}
        )

    def test_corrupt_state_file_fails_open_and_warns(self):
        path = os.path.join(self.root, "logs", "memory_gate.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write("{not valid json")

        err = io.StringIO()
        with redirect_stderr(err):
            state = self.status.load()

        self.assertEqual(state, {})
        self.assertIn(path, err.getvalue())
        self.assertIn("warning", err.getvalue())

    def test_save_leaves_no_tmp_file_and_writes_via_replace(self):
        with patch("os.replace", side_effect=os.replace) as replace:
            self.status.save({"cap": None, "pool_share": 0.1})
        target = os.path.join(self.root, "logs", "memory_gate.json")
        replace.assert_called_once()
        self.assertEqual(replace.call_args[0][1], target)
        leftover = glob.glob(os.path.join(self.root, "logs", "memory_gate.json.*.tmp"))
        self.assertEqual(leftover, [])
        with open(target) as f:
            self.assertEqual(
                f.read(), '{\n  "cap": null,\n  "pool_share": 0.1\n}'
            )


if __name__ == "__main__":
    unittest.main()
