import unittest

from lightcycle.domain.workspace import current_run_index, phase_key


class TestCurrentRunIndex(unittest.TestCase):
    def test_no_steps_yet_is_the_first_run(self):
        self.assertEqual(current_run_index([]), 1)

    def test_a_phase_seen_once_is_its_first_run(self):
        self.assertEqual(current_run_index(["spec"]), 1)

    def test_consecutive_steps_of_one_phase_stay_in_the_same_run(self):
        self.assertEqual(current_run_index(["spec", "spec", "spec"]), 1)

    def test_a_phase_re_entered_after_another_phase_is_its_second_run(self):
        self.assertEqual(current_run_index(["spec", "feature", "code", "spec"]), 2)

    def test_each_further_re_entry_increments_the_run(self):
        phases = ["spec", "feature", "spec", "feature", "spec"]
        self.assertEqual(current_run_index(phases), 3)

    def test_an_earlier_phase_returning_does_not_count_a_later_phase(self):
        self.assertEqual(current_run_index(["spec", "feature", "spec", "feature"]), 2)

    def test_an_unphased_step_does_not_index(self):
        self.assertEqual(current_run_index(["spec", None]), 1)


class TestPhaseKey(unittest.TestCase):
    def test_the_first_run_keys_on_the_bare_phase(self):
        self.assertEqual(phase_key("spec", 1), "spec")

    def test_a_later_run_carries_its_index(self):
        self.assertEqual(phase_key("spec", 3), "spec-3")

    def test_no_phase_keys_to_nothing(self):
        self.assertIsNone(phase_key(None, 4))
