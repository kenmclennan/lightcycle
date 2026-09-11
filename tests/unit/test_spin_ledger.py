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


if __name__ == "__main__":
    unittest.main()
