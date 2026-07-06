import unittest

from the_grid.domain.pool import Breaker


class TestBreaker(unittest.TestCase):
    def test_closed_by_default(self):
        b = Breaker()
        self.assertFalse(b.is_open)
        self.assertIsNone(b.spawn_cap(now=100, alive_count=0))

    def test_from_state_round_trips(self):
        b = Breaker.from_state({"open": True, "reset_at": 500})
        self.assertTrue(b.is_open)
        self.assertEqual(b.reset_at, 500)
        self.assertEqual(b.as_dict(), {"open": True, "reset_at": 500})

    def test_trip_opens_with_reset_at(self):
        b = Breaker().trip(500)
        self.assertTrue(b.is_open)
        self.assertEqual(b.reset_at, 500)

    def test_open_pre_reset_spawns_nothing(self):
        b = Breaker().trip(500)
        self.assertEqual(b.spawn_cap(now=100, alive_count=0), 0)
        self.assertFalse(b.is_probing(now=100))

    def test_open_at_reset_allows_exactly_one_probe(self):
        b = Breaker().trip(500)
        self.assertEqual(b.spawn_cap(now=500, alive_count=0), 1)
        self.assertTrue(b.is_probing(now=500))

    def test_open_past_reset_with_a_probe_already_out_allows_no_more(self):
        b = Breaker().trip(500)
        self.assertEqual(b.spawn_cap(now=600, alive_count=1), 0)

    def test_close_clears_state(self):
        b = Breaker().trip(500).close()
        self.assertFalse(b.is_open)
        self.assertIsNone(b.reset_at)
        self.assertIsNone(b.spawn_cap(now=600, alive_count=0))


if __name__ == "__main__":
    unittest.main()
