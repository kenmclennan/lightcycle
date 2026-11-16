import unittest

from lightcycle.application.pool.observe_sleep import ObserveSleepUseCase
from lightcycle.adapters.sleep_ledger import SleepLedgerAdapter
from tests.support.fake_sleep_ledger import FakeSleepLedger


class TestObserveSleep(unittest.TestCase):
    def test_a_two_hour_wall_jump_records_one_interval_and_persists_the_sample(self):
        ledger = FakeSleepLedger()
        use_case = ObserveSleepUseCase(ledger)
        self.assertEqual(use_case.execute(1000.0, 100.0), ())

        sleeps = use_case.execute(8200.0, 200.0)

        self.assertEqual(sleeps, ((1100.0, 8200.0),))
        self.assertEqual(ledger.load()["sample"], [8200.0, 200.0])

    def test_a_second_call_without_a_jump_records_nothing_more(self):
        ledger = FakeSleepLedger()
        use_case = ObserveSleepUseCase(ledger)
        use_case.execute(1000.0, 100.0)
        use_case.execute(8200.0, 200.0)

        self.assertEqual(use_case.execute(8205.0, 205.0), ((1100.0, 8200.0),))

    def test_an_interval_past_the_retention_horizon_is_pruned(self):
        ledger = FakeSleepLedger({"sample": [1000.0, 100.0], "sleeps": [[10.0, 20.0]]})

        sleeps = ObserveSleepUseCase(ledger).execute(1000.0 + 90000.0, 100.0 + 90000.0)

        self.assertEqual(sleeps, ())

    def test_a_recent_interval_survives_the_prune(self):
        ledger = FakeSleepLedger({"sample": [1000.0, 100.0], "sleeps": [[900.0, 950.0]]})

        sleeps = ObserveSleepUseCase(ledger).execute(1005.0, 105.0)

        self.assertEqual(sleeps, ((900.0, 950.0),))


class TestSleepLedgerAdapter(unittest.TestCase):
    def test_an_unreadable_ledger_loads_as_empty(self):
        import os
        import tempfile

        root = tempfile.mkdtemp()
        with open(os.path.join(root, "sleep-ledger.json"), "w") as f:
            f.write("not json")

        class _Config:
            def data_root(self):
                return root

        ledger = SleepLedgerAdapter(_Config())

        self.assertEqual(ledger.load(), {})
        ledger.save({"sample": [1.0, 2.0], "sleeps": []})
        self.assertEqual(ledger.load()["sample"], [1.0, 2.0])


if __name__ == "__main__":
    unittest.main()
