import unittest

from lightcycle.domain.work import refuse_fields, refuse_state


class TestRefuseFields(unittest.TestCase):
    def test_a_step_field_on_an_item_names_both_structures(self):
        self.assertEqual(
            refuse_fields("item", {"needs"}), "--needs belongs to a step, not an item"
        )

    def test_an_item_field_on_a_step_names_both_structures(self):
        self.assertEqual(
            refuse_fields("step", {"description"}),
            "--description belongs to an item, not a step",
        )

    def test_several_wrong_fields_are_listed_together_and_agree_in_number(self):
        self.assertEqual(
            refuse_fields("item", {"needs", "reason"}),
            "--needs, --reason belong to a step, not an item",
        )

    def test_a_field_of_neither_structure_says_so(self):
        self.assertEqual(
            refuse_fields("item", {"goal"}), "--goal belongs to no structure"
        )

    def test_fields_the_type_owns_are_accepted(self):
        self.assertIsNone(refuse_fields("item", {"title", "description"}))
        self.assertIsNone(refuse_fields("step", {"title", "notes"}))

    def test_no_fields_at_all_is_accepted(self):
        self.assertIsNone(refuse_fields("step", set()))


class TestRefuseState(unittest.TestCase):
    def test_a_park_is_refused_on_an_item_and_names_what_it_takes(self):
        self.assertEqual(
            refuse_state("item", "blocked"),
            "--state blocked applies to a step, not an item; "
            "an item takes --state active, --state in_progress",
        )

    def test_activation_is_refused_on_a_step_and_names_what_it_takes(self):
        self.assertEqual(
            refuse_state("step", "active"),
            "--state active applies to an item, not a step; "
            "a step takes --state blocked, --state ready",
        )

    def test_an_unknown_state_lists_every_state(self):
        self.assertEqual(
            refuse_state("item", "bogus"),
            "unknown --state 'bogus'; use active, blocked, in_progress, ready",
        )

    def test_a_state_the_type_owns_is_accepted(self):
        self.assertIsNone(refuse_state("item", "active"))
        self.assertIsNone(refuse_state("step", "ready"))

    def test_no_state_at_all_is_accepted(self):
        self.assertIsNone(refuse_state("item", None))


if __name__ == "__main__":
    unittest.main()
