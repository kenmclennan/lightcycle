import unittest

from lightcycle.domain.pool.spin_ledger import SpinLedger


class TestRecordDeathIdempotency(unittest.TestCase):
    def test_first_seen_spawnid_increments_the_count(self):
        ledger = SpinLedger().record_death("b-1", now=100, last_line="x", spawnid="sp-1")
        self.assertEqual(ledger.entry("b-1").count, 1)

    def test_same_spawnid_recorded_twice_increments_only_once(self):
        ledger = SpinLedger().record_death("b-1", now=100, last_line="x", spawnid="sp-1")
        ledger = ledger.record_death("b-1", now=101, last_line="x", spawnid="sp-1")
        self.assertEqual(ledger.entry("b-1").count, 1)

    def test_a_different_spawnid_after_a_prior_one_increments_again(self):
        ledger = SpinLedger().record_death("b-1", now=100, last_line="x", spawnid="sp-1")
        ledger = ledger.record_death("b-1", now=101, last_line="x", spawnid="sp-2")
        self.assertEqual(ledger.entry("b-1").count, 2)

    def test_last_spawnid_round_trips_through_as_dict_and_from_state(self):
        ledger = SpinLedger().record_death("b-1", now=100, last_line="x", spawnid="sp-1")
        restored = SpinLedger.from_state(ledger.as_dict())
        self.assertEqual(restored.entry("b-1").last_spawnid, "sp-1")


class TestExitCounter(unittest.TestCase):
    def test_record_exit_increments_and_dedupes_by_spawnid(self):
        ledger = SpinLedger().record_exit("b-1", 100, "x", "sp-1")
        ledger = ledger.record_exit("b-1", 101, "x", "sp-1")
        self.assertEqual(ledger.exits["b-1"].count, 1)
        ledger = ledger.record_exit("b-1", 102, "x", "sp-2")
        self.assertEqual(ledger.exits["b-1"].count, 2)

    def test_should_park_exit_is_true_exactly_at_the_cap(self):
        ledger = SpinLedger().record_exit("b-1", 100, "x", "sp-1").record_exit("b-1", 101, "x", "sp-2")
        self.assertFalse(ledger.should_park_exit("b-1", 3))
        ledger = ledger.record_exit("b-1", 102, "x", "sp-3")
        self.assertTrue(ledger.should_park_exit("b-1", 3))

    def test_clear_removes_both_entries(self):
        ledger = SpinLedger().record_death("b-1", 1, "x", "a").record_exit("b-1", 1, "x", "b")
        cleared = ledger.clear("b-1")
        self.assertEqual((cleared.steps, cleared.exits), ({}, {}))

    def test_record_activity_leaves_the_exit_entry(self):
        ledger = SpinLedger().record_exit("b-1", 1, "x", "b").record_activity("b-1")
        self.assertIn("b-1", ledger.exits)

    def test_a_state_without_an_exits_key_loads(self):
        self.assertEqual(SpinLedger.from_state({}).exits, {})
        self.assertEqual(SpinLedger.from_state({"steps": {}}).exits, {})

    def test_exits_round_trip_through_as_dict_and_from_state(self):
        ledger = SpinLedger().record_exit("b-1", 100, "x", "sp-1")
        self.assertEqual(SpinLedger.from_state(ledger.as_dict()).exits, ledger.exits)

    def test_drop_exits_keeps_only_the_named_steps(self):
        ledger = SpinLedger().record_exit("a", 1, "x", "s").record_exit("b", 1, "x", "t")
        self.assertEqual(set(ledger.drop_exits({"a"}).exits), {"a"})



if __name__ == "__main__":
    unittest.main()

