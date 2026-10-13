import os
import tempfile
import unittest

from lightcycle.adapters.drain import PoolDrainAdapter


class TestPoolDrainAdapter(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

        class Config:
            def data_root(inner):
                return self._tmp.name

        self.adapter = PoolDrainAdapter(Config())

    def test_request_requested_and_clear_round_trip_on_disk(self):
        self.assertFalse(self.adapter.requested())
        self.adapter.request()
        self.adapter.request()
        self.assertTrue(self.adapter.requested())
        self.assertTrue(os.path.exists(os.path.join(self._tmp.name, ".lc-drain")))
        self.adapter.clear()
        self.assertFalse(self.adapter.requested())

    def test_clear_on_a_missing_file_is_a_no_op(self):
        self.adapter.clear()
        self.assertFalse(self.adapter.requested())



if __name__ == "__main__":
    unittest.main()
