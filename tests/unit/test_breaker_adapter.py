import tempfile
import unittest

from the_grid.adapters.breaker import BreakerAdapter


class FakeConfig:
    def __init__(self, root):
        self._root = root

    def grid_root(self):
        return self._root

    def data_root(self):
        return self._root

    def library_root(self):
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


if __name__ == "__main__":
    unittest.main()
