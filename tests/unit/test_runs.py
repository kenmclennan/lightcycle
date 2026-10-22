import unittest

from lightcycle.domain.runs import Pass, PhaseRun, RunState, pass_id, run_id, run_round


class TestIds(unittest.TestCase):
    def test_a_pass_id_names_its_item_and_number(self):
        self.assertEqual(pass_id("LC-1", 3), "LC-1.p3")

    def test_a_run_id_names_its_pass_and_phase(self):
        self.assertEqual(run_id("LC-1.p3", "code"), "LC-1.p3.code")

    def test_a_phaseless_run_still_has_a_stable_id(self):
        self.assertEqual(run_id("LC-1.p1", None), "LC-1.p1.-")

    def test_two_passes_of_one_item_never_collide(self):
        self.assertNotEqual(pass_id("LC-1", 1), pass_id("LC-1", 2))

    def test_the_same_phase_in_two_passes_never_collides(self):
        self.assertNotEqual(
            run_id(pass_id("LC-1", 1), "code"), run_id(pass_id("LC-1", 2), "code")
        )


class TestRounds(unittest.TestCase):
    def test_round_one_keeps_the_plain_id(self):
        self.assertEqual(run_id("LC-1.p1", "amend", 1), run_id("LC-1.p1", "amend"))
        self.assertEqual(run_id("LC-1.p1", "amend", 1), "LC-1.p1.amend")

    def test_round_two_appends_a_round_suffix(self):
        self.assertEqual(run_id("LC-1.p1", "amend", 2), "LC-1.p1.amend.r2")

    def test_a_phaseless_round_two_has_a_stable_id(self):
        self.assertEqual(run_id("LC-1.p1", None, 2), "LC-1.p1.-.r2")

    def test_run_round_round_trips_both_forms(self):
        self.assertEqual(run_round(run_id("LC-1.p1", "amend", 1)), 1)
        self.assertEqual(run_round(run_id("LC-1.p1", "amend", 3)), 3)
        self.assertEqual(run_round(run_id("LC-1.p1", None, 12)), 12)

    def test_a_phase_run_reads_its_round_from_its_id(self):
        self.assertEqual(PhaseRun("LC-1.p1.amend", "LC-1", "LC-1.p1", "amend").round, 1)
        self.assertEqual(PhaseRun("LC-1.p1.amend.r2", "LC-1", "LC-1.p1", "amend").round, 2)


class TestOpenness(unittest.TestCase):
    def test_a_new_pass_is_open(self):
        self.assertTrue(Pass("LC-1.p1", "LC-1", 1).is_open)

    def test_a_closed_pass_is_not_open(self):
        self.assertFalse(Pass("LC-1.p1", "LC-1", 1, state="closed").is_open)

    def test_a_new_run_is_open(self):
        self.assertTrue(PhaseRun("r", "LC-1", "LC-1.p1").is_open)

    def test_a_merged_run_is_not_open(self):
        self.assertFalse(PhaseRun("r", "LC-1", "LC-1.p1", state=RunState.MERGED).is_open)

    def test_an_abandoned_run_is_not_open(self):
        self.assertFalse(PhaseRun("r", "LC-1", "LC-1.p1", state=RunState.ABANDONED).is_open)


class TestAsDict(unittest.TestCase):
    def test_as_dict_aliases_pass_id_as_pass(self):
        r = PhaseRun("r", "LC-1", "LC-1.p1", phase="spec")
        d = r.as_dict()
        self.assertEqual(d["pass"], "LC-1.p1")
        self.assertEqual(d["pass_id"], "LC-1.p1")


if __name__ == "__main__":
    unittest.main()
