import unittest

from tests.support.harness import DEFAULT_WORKFLOW, Harness
from tests.support.step_factory import create_owned_step

LONG = " ".join("word%d" % i for i in range(35)) + "."
SHORT = "worth keeping"


def _activated(h):
    item = h.store.create_item("an item", "a description")
    rc, out, err = h.run(
        "set", item, "--state", "active", "--workflow", DEFAULT_WORKFLOW, "--step", "build"
    )
    assert rc == 0, err
    return item, out.strip()


class TestDoneOnAStep(unittest.TestCase):
    def setUp(self):
        self.h = Harness(["coder", "reviewer"])
        self.item, self.step = _activated(self.h)

    def test_over_long_note_is_refused_and_the_step_is_left_open(self):
        rc, out, err = self.h.run("done", self.step, "done", "--note", LONG)
        self.assertEqual(rc, 2)
        self.assertTrue(err.startswith("refused:"))
        self.assertIn("--note, rule 3", err)
        self.assertEqual(out, "")
        step = self.h.store.get_step(self.step)
        self.assertNotEqual(step.state, "done")
        self.assertNotIn("word0", step.notes or "")

    def test_the_same_command_with_a_short_note_succeeds_and_stores_it(self):
        rc, out, err = self.h.run("done", self.step, "done", "--note", SHORT)
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.h.store.get_step(self.step).state, "done")
        self.assertIn(SHORT, self.h.store.get_step(out.strip()).notes)

    def test_a_compliant_done_still_prints_the_next_step_id(self):
        rc, out, err = self.h.run("done", self.step, "done", "--note", SHORT)
        self.assertEqual(rc, 0, err)
        self.assertTrue(out.strip())

    def test_multiple_note_words_are_counted_as_one_joined_text(self):
        words = LONG.split()
        rc, out, err = self.h.run("done", self.step, "done", "--note", *words)
        self.assertEqual(rc, 2)
        self.assertIn("rule 3", err)


class TestDoneOnAnItem(unittest.TestCase):
    def setUp(self):
        self.h = Harness(["coder", "reviewer"])
        self.item = self.h.store.create_item("an item", "a description")

    def test_over_long_note_leaves_the_item_open(self):
        rc, out, err = self.h.run(
            "done", self.item, "done", "--note", LONG, "--disposition", "completed"
        )
        self.assertEqual(rc, 2)
        self.assertIn("--note, rule 3", err)
        self.assertEqual(out, "")
        self.assertNotEqual(self.h.store.get_node(self.item).state, "done")

    def test_short_note_closes_the_item_and_is_stored(self):
        rc, out, err = self.h.run(
            "done", self.item, "done", "--note", SHORT, "--disposition", "completed"
        )
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.h.store.get_node(self.item).note, SHORT)

    def test_cap_refusal_comes_before_the_undeclared_outcome_refusal(self):
        rc, out, err = self.h.run("done", self.item, "no-such-outcome", "--note", LONG)
        self.assertEqual(rc, 2)
        self.assertTrue(err.startswith("refused:"))
        self.assertNotIn("not bundle-declared", err)


class TestCloseRefusesAnOverLongNote(unittest.TestCase):
    def setUp(self):
        self.h = Harness(["coder", "reviewer"])
        self.item = self.h.store.create_item("an item", "a description")

    def test_item_stays_open(self):
        rc, out, err = self.h.run("close", self.item, "--note", LONG)
        self.assertEqual(rc, 2)
        self.assertIn("--note, rule 3", err)
        self.assertEqual(out, "")
        self.assertNotEqual(self.h.store.get_node(self.item).state, "done")

    def test_short_note_closes_and_is_stored(self):
        rc, out, err = self.h.run("close", self.item, "--note", SHORT)
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.h.store.get_node(self.item).note, SHORT)

    def test_a_step_given_to_close_reports_that_refusal_not_a_cap(self):
        step = create_owned_step(self.h.store, "build: x", step="build", role="agent")
        rc, out, err = self.h.run("close", step, "--note", LONG)
        self.assertEqual(rc, 2)
        self.assertIn("lc done", err)
        self.assertNotIn("refused:", err)


class TestNewStepRefusesAnOverLongNote(unittest.TestCase):
    def setUp(self):
        self.h = Harness(["coder", "reviewer"])
        self.item, _ = _activated(self.h)

    def _step_count(self):
        return len(self.h.store.all_nodes())

    def test_no_step_is_created(self):
        before = self._step_count()
        rc, out, err = self.h.run(
            "new", "step", "", "--step", "build", "--parent", self.item, "--note", LONG
        )
        self.assertEqual(rc, 2)
        self.assertIn("--note, rule 3", err)
        self.assertEqual(out, "")
        self.assertEqual(self._step_count(), before)

    def test_short_note_creates_the_step(self):
        before = self._step_count()
        rc, out, err = self.h.run(
            "new", "step", "", "--step", "build", "--parent", self.item, "--note", SHORT
        )
        self.assertEqual(rc, 0, err)
        self.assertEqual(self._step_count(), before + 1)

    def test_missing_parent_reports_that_refusal_not_a_cap(self):
        rc, out, err = self.h.run(
            "new", "step", "", "--step", "build", "--note", LONG
        )
        self.assertEqual(rc, 2)
        self.assertIn("--parent", err)
        self.assertNotIn("refused:", err)


class TestSetWaitingRefusesOverLongParkFields(unittest.TestCase):
    def setUp(self):
        self.h = Harness(["coder", "reviewer"])
        _, self.step = _activated(self.h)

    def _park(self):
        return self.h.store.get_step(self.step).park

    def test_one_long_field_is_refused_naming_only_that_field(self):
        rc, out, err = self.h.run(
            "set", self.step, "--state", "waiting", "--needs", LONG, "--reason", "short one"
        )
        self.assertEqual(rc, 2)
        self.assertIn("--needs, rule 3", err)
        self.assertNotIn("--reason", err)
        self.assertNotIn("--tried", err)
        self.assertEqual(out, "")
        self.assertFalse(self._park())

    def test_two_long_fields_are_refused_in_one_message_naming_both(self):
        rc, out, err = self.h.run(
            "set", self.step, "--state", "waiting", "--needs", LONG, "--reason", LONG,
            "--tried", "short one",
        )
        self.assertEqual(rc, 2)
        self.assertEqual(err.count("refused:"), 1)
        self.assertIn("--needs, rule 3", err)
        self.assertIn("--reason, rule 3", err)
        self.assertNotIn("--tried, rule", err)
        self.assertFalse(self._park())

    def test_a_long_tried_is_refused(self):
        rc, out, err = self.h.run(
            "set", self.step, "--state", "waiting", "--needs", "decide X",
            "--reason", "needed a decision", "--tried", LONG,
        )
        self.assertEqual(rc, 2)
        self.assertIn("--tried, rule 3", err)

    def test_three_clean_fields_are_written(self):
        rc, out, err = self.h.run(
            "set", self.step, "--state", "waiting", "--needs", "decide X",
            "--reason", "needed a decision", "--tried", "two options",
        )
        self.assertEqual(rc, 0, err)
        self.assertEqual(self._park().needs, "decide X")
        self.assertEqual(self._park().tried, "two options")

    def test_missing_reason_reports_that_refusal_not_a_cap(self):
        rc, out, err = self.h.run(
            "set", self.step, "--state", "waiting", "--needs", LONG
        )
        self.assertEqual(rc, 2)
        self.assertIn("--reason", err)
        self.assertNotIn("refused:", err)

    def test_free_form_notes_are_never_refused(self):
        rc, out, err = self.h.run("set", self.step, "--notes", LONG)
        self.assertEqual(rc, 0, err)


class TestUnknownIdReportsThatRefusal(unittest.TestCase):
    def test_every_verb_reports_unknown_id_and_no_cap(self):
        h = Harness(["coder", "reviewer"])
        for verb, args in (
            ("done", ("done", "--note", LONG)),
            ("close", ("--note", LONG)),
            ("set", ("--state", "waiting", "--needs", LONG, "--reason", LONG)),
        ):
            rc, out, err = h.run(verb, "NOPE-1", *args)
            self.assertNotEqual(rc, 0, verb)
            self.assertIn("unknown node", err, verb)
            self.assertNotIn("refused:", err, verb)


if __name__ == "__main__":
    unittest.main()
