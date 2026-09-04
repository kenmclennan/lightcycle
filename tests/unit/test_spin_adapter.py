import io
import os
import tempfile
import unittest
from contextlib import redirect_stderr

from lightcycle.adapters.spin import SpinAdapter


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
        self.assertEqual(state, {})
        self.assertEqual(err.getvalue(), "")

    def test_save_then_load_round_trips(self):
        self.spin.save({"pool": {"streak": 2, "tripped": False}})
        self.assertEqual(self.spin.load(), {"pool": {"streak": 2, "tripped": False}})

    def test_corrupt_state_file_is_empty_and_warns(self):
        path = os.path.join(self.root, "logs", "spin.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write("{not valid json")

        err = io.StringIO()
        with redirect_stderr(err):
            state = self.spin.load()

        self.assertEqual(state, {})
        self.assertIn(path, err.getvalue())
        self.assertIn("warning", err.getvalue())


if __name__ == "__main__":
    unittest.main()
