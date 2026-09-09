import glob
import io
import os
import tempfile
import unittest
from contextlib import redirect_stderr
from unittest.mock import patch

from lightcycle.adapters.breaker import BreakerAdapter


class FakeConfig:
    def __init__(self, root):
        self._root = root

    def engine_root(self):
        return self._root

    def data_root(self):
        return self._root

    def prompts_root(self):
        return self._root


class TestBreakerAdapter(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.breaker = BreakerAdapter(FakeConfig(self.root))

    def test_load_with_no_state_file_is_empty(self):
        self.assertEqual(self.breaker.load(), {})

    def test_save_then_load_round_trips(self):
        self.breaker.save({"open": True, "reset_at": 12345})
        self.assertEqual(self.breaker.load(), {"open": True, "reset_at": 12345})

    def test_state_survives_a_new_adapter_instance(self):
        self.breaker.save({"open": True, "reset_at": 12345})
        reloaded = BreakerAdapter(FakeConfig(self.root))
        self.assertEqual(reloaded.load(), {"open": True, "reset_at": 12345})

    def test_corrupt_state_file_fails_closed_and_warns(self):
        path = os.path.join(self.root, "logs", "breaker.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write("{not valid json")

        err = io.StringIO()
        with redirect_stderr(err):
            state = self.breaker.load()

        self.assertEqual(state, {"open": True, "reset_at": 0})
        self.assertIn(path, err.getvalue())
        self.assertIn("warning", err.getvalue())

    def test_save_leaves_no_tmp_file_and_writes_via_replace(self):
        with patch("os.replace", side_effect=os.replace) as replace:
            self.breaker.save({"open": True, "reset_at": 12345})
        target = os.path.join(self.root, "logs", "breaker.json")
        replace.assert_called_once()
        self.assertEqual(replace.call_args[0][1], target)
        leftover = glob.glob(os.path.join(self.root, "logs", "breaker.json.*.tmp"))
        self.assertEqual(leftover, [])
        with open(target) as f:
            self.assertEqual(f.read(), '{\n  "open": true,\n  "reset_at": 12345\n}')


if __name__ == "__main__":
    unittest.main()
