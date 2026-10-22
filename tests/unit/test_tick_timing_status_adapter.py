import os
import tempfile
import unittest
from unittest import mock

from lightcycle.adapters.tick_timing_status import TickTimingStatusAdapter
from lightcycle.domain.pool import TickTiming


class _Config:
    def __init__(self, root):
        self._root = root

    def data_root(self):
        return self._root


class TestTickTimingStatusAdapter(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = self._tmp.name
        self.adapter = TickTimingStatusAdapter(_Config(self.root))
        self.path = os.path.join(self.root, "tick-timing.json")

    def test_save_then_load_round_trips_at_the_data_root(self):
        t = TickTiming(7, 5.0, ((1.0, 2.0),))
        self.adapter.save(t)
        self.assertTrue(os.path.exists(self.path))
        self.assertEqual(self.adapter.load(), t)

    def test_missing_file_loads_none(self):
        self.assertIsNone(self.adapter.load())

    def test_invalid_json_list_and_partial_dict_load_none(self):
        for body in ("{not json", "[1, 2]", '{"pid": 1}'):
            with open(self.path, "w") as f:
                f.write(body)
            with mock.patch("sys.stderr"):
                self.assertIsNone(self.adapter.load(), body)

    def test_a_failed_replace_leaves_the_previous_file_intact(self):
        old = TickTiming(7, 5.0, ((1.0, 2.0),))
        self.adapter.save(old)
        with mock.patch("os.replace", side_effect=OSError("boom")), mock.patch("sys.stderr"):
            self.adapter.save(TickTiming(7, 9.0, ((8.0, 1.0),)))
        self.assertEqual(self.adapter.load(), old)
        self.assertEqual(
            sorted(n for n in os.listdir(self.root) if n != "tick-timing.json"),
            ["tick-timing.json.%d.tmp" % os.getpid()])

    def test_a_failed_write_does_not_raise(self):
        blocker = os.path.join(self.root, "blocker")
        open(blocker, "w").close()
        adapter = TickTimingStatusAdapter(_Config(os.path.join(blocker, "sub")))
        with mock.patch("sys.stderr"):
            adapter.save(TickTiming(7, 5.0, ()))
