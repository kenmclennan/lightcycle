import unittest

from lightcycle.domain.work import (
    FieldRefusal, StateRefusal, refuse_fields, refuse_state, render_field_refusal,
)


class TestRefuseFields(unittest.TestCase):
    def test_a_step_field_on_an_item_names_both_structures(self):
        self.assertEqual(
            refuse_fields("item", {"needs"}),
            FieldRefusal(fields=("needs",), requested_type="item", owner="step"),
        )

    def test_an_item_field_on_a_step_names_both_structures(self):
        self.assertEqual(
            refuse_fields("step", {"description"}),
            FieldRefusal(fields=("description",), requested_type="step", owner="item"),
        )

    def test_several_wrong_fields_are_listed_together_and_agree_in_number(self):
        self.assertEqual(
            refuse_fields("item", {"needs", "reason"}),
            FieldRefusal(fields=("needs", "reason"), requested_type="item", owner="step"),
        )

    def test_a_field_of_neither_structure_says_so(self):
        self.assertEqual(
            refuse_fields("item", {"goal"}),
            FieldRefusal(fields=("goal",), requested_type="item", owner=None),
        )

    def test_fields_the_type_owns_are_accepted(self):
        self.assertIsNone(refuse_fields("item", {"title", "description"}))
        self.assertIsNone(refuse_fields("step", {"title", "notes"}))

    def test_depends_is_owned_by_item(self):
        self.assertIsNone(refuse_fields("item", {"depends"}))

    def test_no_fields_at_all_is_accepted(self):
        self.assertIsNone(refuse_fields("step", set()))


class TestRenderFieldRefusal(unittest.TestCase):
    def test_a_single_wrong_field_names_both_structures(self):
        refusal = FieldRefusal(fields=("description",), requested_type="step", owner="item")
        self.assertEqual(
            render_field_refusal(refusal), "--description belongs to an item, not a step"
        )

    def test_several_wrong_fields_agree_in_number(self):
        refusal = FieldRefusal(fields=("needs", "reason"), requested_type="item", owner="step")
        self.assertEqual(
            render_field_refusal(refusal), "--needs, --reason belong to a step, not an item"
        )

    def test_a_field_owned_by_neither_structure_says_so(self):
        refusal = FieldRefusal(fields=("goal",), requested_type="item", owner=None)
        self.assertEqual(render_field_refusal(refusal), "--goal belongs to no structure")


class TestRefuseState(unittest.TestCase):
    def test_a_park_is_refused_on_an_item_and_names_what_it_takes(self):
        self.assertEqual(
            refuse_state("item", "waiting"),
            StateRefusal(
                state="waiting", requested_type="item", owner="step",
                allowed=("active", "in_progress"),
            ),
        )

    def test_activation_is_refused_on_a_step_and_names_what_it_takes(self):
        self.assertEqual(
            refuse_state("step", "active"),
            StateRefusal(
                state="active", requested_type="step", owner="item",
                allowed=("ready", "waiting"),
            ),
        )

    def test_an_unknown_state_lists_every_state(self):
        self.assertEqual(
            refuse_state("item", "bogus"),
            StateRefusal(
                state="bogus", requested_type="item", owner=None,
                allowed=("active", "in_progress", "ready", "waiting"),
            ),
        )

    def test_a_state_the_type_owns_is_accepted(self):
        self.assertIsNone(refuse_state("item", "active"))
        self.assertIsNone(refuse_state("step", "ready"))

    def test_no_state_at_all_is_accepted(self):
        self.assertIsNone(refuse_state("item", None))


if __name__ == "__main__":
    unittest.main()
