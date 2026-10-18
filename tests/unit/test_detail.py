import unittest
from types import SimpleNamespace

from lightcycle.application.workflows.bundle_check import check_bundle_references
from lightcycle.domain.work.detail import (
    DetailEntry,
    default_detail,
    detail_presents,
    detail_shape_problem,
    detail_value_is_url,
    legacy_presents_key,
    parse_detail,
    resolve_detail,
    with_park,
)


class TestGrammar(unittest.TestCase):
    def test_a_bracketed_list_splits_on_commas(self):
        self.assertEqual(
            parse_detail("[pr, report, in:findings]"), ("pr", "report", "in:findings"))

    def test_anything_not_a_bracketed_list_does_not_parse(self):
        for bad in (None, "pr", "", "[]", {"pr": 1}):
            self.assertIsNone(parse_detail(bad), repr(bad))

    def test_shape_problems_are_named(self):
        self.assertIn("bracketed", detail_shape_problem("pr, report"))
        self.assertIn("empty", detail_shape_problem("[]"))
        self.assertIn("twice", detail_shape_problem("[pr, pr]"))
        self.assertIsNone(detail_shape_problem("[pr, report]"))


class TestDefaultAndResolution(unittest.TestCase):
    def test_default_list_adds_pr_with_a_run(self):
        self.assertEqual(default_detail(False), ("outcome", "report"))
        self.assertEqual(default_detail(True), ("outcome", "report", "pr"))

    def test_a_parked_step_leads_with_reason_and_needs_after_the_declared_names(self):
        self.assertEqual(
            with_park(("outcome", "out:check-report"), True),
            ("reason", "needs", "outcome", "out:check-report"))

    def test_park_entries_declared_already_are_not_duplicated(self):
        self.assertEqual(
            with_park(("outcome", "needs", "reason"), True), ("reason", "needs", "outcome"))

    def test_a_step_not_parked_keeps_its_declared_names(self):
        self.assertEqual(
            with_park(("outcome", "needs"), False), ("outcome", "needs"))

    def test_the_default_list_on_a_parked_step_yields_reason_and_needs_once(self):
        self.assertEqual(
            with_park(default_detail(True), True),
            ("reason", "needs", "outcome", "report", "pr"))

    def test_a_legacy_presents_becomes_the_leading_default_entry(self):
        self.assertEqual(default_detail(False, "pr"), ("pr", "outcome", "report"))
        self.assertEqual(default_detail(True, "pr"), ("outcome", "report", "pr"))
        self.assertEqual(
            default_detail(False, "description"), ("in:description", "outcome", "report"))
        self.assertEqual(
            default_detail(False, "artifact:findings"),
            ("in:findings", "outcome", "report"))
        self.assertEqual(default_detail(False, "in:findings"), ("outcome", "report"))

    def test_legacy_presents_key_translates_only_the_legacy_forms(self):
        self.assertEqual(legacy_presents_key("pr"), "pr")
        self.assertEqual(legacy_presents_key("description"), "in:description")
        self.assertEqual(legacy_presents_key("artifact:findings"), "in:findings")
        for other in (None, "report", "in:findings", "artifact:"):
            self.assertIsNone(legacy_presents_key(other), repr(other))

    def test_presents_translates_a_legacy_form_to_its_entry_key(self):
        entries = [DetailEntry("outcome", "field"), DetailEntry("in:findings", "input", "F")]
        self.assertEqual(detail_presents("artifact:findings", entries), "in:findings")

    def test_resolve_reads_each_namespace_and_keeps_absent_names_as_none(self):
        entries = resolve_detail(
            ("pr", "in:findings", "out:summary", "needs"),
            {"pr": "http://x"}, {"findings": "F"}, {"summary": "S"})
        self.assertEqual(entries, [
            DetailEntry("pr", "field", "http://x"),
            DetailEntry("in:findings", "input", "F"),
            DetailEntry("out:summary", "output", "S"),
            DetailEntry("needs", "field", None),
        ])

    def test_presents_is_the_declared_key_if_listed_else_the_first(self):
        entries = [DetailEntry("pr", "field"), DetailEntry("report", "field")]
        self.assertEqual(detail_presents("report", entries), "report")
        self.assertEqual(detail_presents("description", entries), "pr")
        self.assertEqual(detail_presents(None, entries), "pr")
        self.assertIsNone(detail_presents(None, []))


WORKFLOW = """# Flow

entry: build

edges:
  build  done  gate
"""


def messages_for(gate_front, build_front=""):
    steps = {
        "build": "---\nmodel: sonnet\n%s---\n# Build\n" % build_front,
        "gate": "---\n%s---\n# Gate\n" % gate_front,
    }
    bundle = SimpleNamespace(steps=steps, workflows={"flow": WORKFLOW})
    return [m for ms in check_bundle_references(bundle).values() for m in ms]


class TestBundleCheck(unittest.TestCase):
    def test_a_valid_detail_passes(self):
        front = "detail: [pr, report, in:findings]\npresents: pr\n"
        build = "produces:\n  findings: optional\n"
        self.assertEqual(messages_for(front, build), [])

    def test_an_unknown_execution_name_names_the_step(self):
        found = messages_for("detail: [pr, bogus]\n")
        self.assertEqual(len(found), 1)
        self.assertIn("'gate'", found[0])
        self.assertIn("bogus", found[0])

    def test_a_list_with_one_valid_and_one_unknown_name_reports_only_the_unknown_one(self):
        found = messages_for("detail: [outcome, nope]\n")
        self.assertEqual(len(found), 1)
        self.assertIn("nope", found[0])
        self.assertNotIn("outcome", found[0])

    def test_out_must_be_in_the_steps_own_produces(self):
        found = messages_for("detail: [out:summary]\n")
        self.assertEqual(len(found), 1)
        self.assertIn("own produces", found[0])

    def test_in_must_be_accepted_produced_or_reserved(self):
        self.assertEqual(len(messages_for("detail: [in:ghost]\n")), 1)
        self.assertEqual(messages_for("detail: [in:description, in:report]\n"), [])
        self.assertEqual(
            messages_for("detail: [in:spec]\naccepts:\n  spec: optional\n"), [])

    def test_a_presents_outside_the_list_names_the_step(self):
        found = messages_for("detail: [pr, report]\npresents: description\n")
        self.assertEqual(len(found), 1)
        self.assertIn("'gate'", found[0])
        self.assertIn("not in the step's detail list", found[0])

    def test_a_malformed_list_is_rejected(self):
        for front in ("detail: pr, report\n", "detail:\n  - pr\n", "detail: []\n",
                      "detail: [pr, pr]\n"):
            with self.subTest(front):
                found = messages_for(front)
                self.assertEqual(len(found), 1)
                self.assertIn("'gate'", found[0])


class TestDetailValueIsUrl(unittest.TestCase):
    def test_a_url_is_accepted(self):
        self.assertTrue(detail_value_is_url("https://example.com/a"))
        self.assertTrue(detail_value_is_url("http://example.com"))

    def test_surrounding_whitespace_is_trimmed(self):
        self.assertTrue(detail_value_is_url("  https://example.com/a\n"))

    def test_a_two_line_value_is_rejected(self):
        self.assertFalse(detail_value_is_url("https://example.com/a\nhttps://example.com/b"))

    def test_a_value_with_a_space_is_rejected(self):
        self.assertFalse(detail_value_is_url("see https://example.com/a"))

    def test_a_bare_domain_is_rejected(self):
        self.assertFalse(detail_value_is_url("example.com"))

    def test_a_path_is_rejected(self):
        self.assertFalse(detail_value_is_url("/tmp/notes.md"))

    def test_an_empty_value_is_rejected(self):
        self.assertFalse(detail_value_is_url(""))
        self.assertFalse(detail_value_is_url(None))


if __name__ == "__main__":
    unittest.main()
