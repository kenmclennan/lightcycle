import unittest

from lightcycle.domain.work.summary_split import split_summary

PROJECTS = {"LC-1329": "lightcycle", "LC-1300": "lightcycle", "YO-7": "yori", "LC-2": "lightcycle"}

WORKED = (
    "Delivered\n"
    "- The report shows a section per project [LC-1329]\n"
    "- Yori opens a note from the list [YO-7, LC-2]\n"
    "- Odd line with no id\n"
    "\n"
    "Fixed\n"
    "- The picker no longer drops today [LC-1300]\n"
    "\n"
    "Improved\n"
    "- Tidied the audit prompt [AUD-9]"
)


class TestSplitSummary(unittest.TestCase):
    def test_the_worked_example_files_bullets_and_keeps_the_rest(self):
        sections, rest = split_summary(WORKED, PROJECTS)

        self.assertEqual(sections["lightcycle"]["Delivered"], ["- The report shows a section per project [LC-1329]"])
        self.assertEqual(sections["lightcycle"]["Fixed"], ["- The picker no longer drops today [LC-1300]"])
        self.assertEqual(sections["yori"]["Delivered"], ["- Yori opens a note from the list [YO-7, LC-2]"])
        self.assertEqual(
            rest, "Delivered\n- Odd line with no id\n\nImproved\n- Tidied the audit prompt [AUD-9]"
        )

    def test_text_with_no_labels_is_returned_unchanged_as_the_remainder(self):
        text = "Closed a handful of items today [LC-1329]."

        sections, rest = split_summary(text, PROJECTS)

        self.assertEqual(sections, {})
        self.assertEqual(rest, text)

    def test_every_bullet_matched_leaves_no_remainder(self):
        sections, rest = split_summary("Delivered\n- One [LC-1329]\n\nFixed\n- Two [YO-7]", PROJECTS)

        self.assertIsNone(rest)
        self.assertEqual(sections["lightcycle"], {"Delivered": ["- One [LC-1329]"]})
        self.assertEqual(sections["yori"], {"Fixed": ["- Two [YO-7]"]})

    def test_no_bullet_matched_leaves_the_text_whole(self):
        text = "Delivered\n- One [AUD-1]\n- Two [AUD-2]"

        sections, rest = split_summary(text, PROJECTS)

        self.assertEqual(sections, {})
        self.assertEqual(rest, text)

    def test_trailing_period_after_the_bracket_still_ends_the_line(self):
        sections, rest = split_summary("Delivered\n- One [LC-1329].", PROJECTS)

        self.assertIsNone(rest)
        self.assertEqual(sections["lightcycle"], {"Delivered": ["- One [LC-1329]."]})

    def test_trailing_period_after_a_multi_id_bracket_still_ends_the_line(self):
        sections, rest = split_summary("Delivered\n- Both [LC-1, LC-2].", {"LC-1": "lightcycle", "LC-2": "lightcycle"})

        self.assertIsNone(rest)
        self.assertEqual(sections["lightcycle"], {"Delivered": ["- Both [LC-1, LC-2]."]})

    def test_a_bracket_followed_by_words_does_not_end_the_line(self):
        sections, rest = split_summary("Delivered\n- One [LC-1329] and more", PROJECTS)

        self.assertEqual(sections, {})
        self.assertEqual(rest, "Delivered\n- One [LC-1329] and more")

    def test_a_bullet_citing_two_projects_files_under_the_first_resolving_id(self):
        sections, _ = split_summary("Delivered\n- Both [YO-7, LC-2]", PROJECTS)

        self.assertEqual(list(sections), ["yori"])

    def test_a_non_resolving_first_id_falls_through_to_a_resolving_second(self):
        sections, rest = split_summary("Delivered\n- Mixed [AUD-9, LC-2]\n- Lost [AUD-9]", PROJECTS)

        self.assertEqual(sections["lightcycle"]["Delivered"], ["- Mixed [AUD-9, LC-2]"])
        self.assertEqual(rest, "Delivered\n- Lost [AUD-9]")

    def test_a_bullet_under_another_heading_stays_in_the_remainder(self):
        text = "Notes\n- Not a section [LC-1329]"

        sections, rest = split_summary(text, PROJECTS)

        self.assertEqual(sections, {})
        self.assertEqual(rest, text)

    def test_a_project_key_of_none_collects_unscoped_items(self):
        sections, _ = split_summary("Fixed\n- Loose [X-1]", {"X-1": None})

        self.assertEqual(sections[None]["Fixed"], ["- Loose [X-1]"])
