import glob
import io
import os
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stderr
from unittest.mock import patch

from lightcycle.adapters.spin import SpinAdapter
from lightcycle.domain.pool import SpinLedger


class FakeConfig:
    def __init__(self, root):
        self._root = root

    def data_root(self):
        return self._root


class TestSpinAdapter(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.spin = SpinAdapter(FakeConfig(self.root))

    def test_load_with_no_state_file_is_empty_and_quiet(self):
        err = io.StringIO()
        with redirect_stderr(err):
            state = self.spin.load()
        self.assertEqual(state, SpinLedger())
        self.assertEqual(err.getvalue(), "")

    def test_save_then_load_round_trips(self):
        self.spin.update(lambda _: SpinLedger(pool_streak=2, pool_tripped=False))
        self.assertEqual(self.spin.load(), SpinLedger(pool_streak=2, pool_tripped=False))

    def test_corrupt_state_file_is_empty_and_warns(self):
        path = os.path.join(self.root, "logs", "spin.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write("{not valid json")

        err = io.StringIO()
        with redirect_stderr(err):
            state = self.spin.load()

        self.assertEqual(state, SpinLedger())
        self.assertIn(path, err.getvalue())
        self.assertIn("warning", err.getvalue())

    def test_save_leaves_no_tmp_file_and_writes_via_replace(self):
        with patch("os.replace", side_effect=os.replace) as replace:
            self.spin.update(lambda _: SpinLedger(pool_streak=2, pool_tripped=False))
        target = os.path.join(self.root, "logs", "spin.json")
        replace.assert_called_once()
        self.assertEqual(replace.call_args[0][1], target)
        leftover = glob.glob(os.path.join(self.root, "logs", "spin.json.*.tmp"))
        self.assertEqual(leftover, [])

    def test_two_updates_racing_for_the_same_file_do_not_lose_either_writers_change(self):
        port = SpinAdapter(FakeConfig(self.root))
        acquired = threading.Event()

        def _slow_mutate(ledger):
            acquired.set()
            time.sleep(0.2)
            return ledger.record_death("step-a", now=100, last_line="a")

        thread = threading.Thread(target=lambda: port.update(_slow_mutate))
        thread.start()
        self.assertTrue(acquired.wait(timeout=5), "first update never started")

        other_port = SpinAdapter(FakeConfig(self.root))
        other_port.update(lambda ledger: ledger.record_death("step-b", now=200, last_line="b"))
        thread.join(timeout=5)

        ledger = port.load()
        self.assertIsNotNone(ledger.entry("step-a"))
        self.assertIsNotNone(ledger.entry("step-b"))


if __name__ == "__main__":
    unittest.main()
