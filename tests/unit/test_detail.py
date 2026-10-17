import unittest
from types import SimpleNamespace

from lightcycle.application.workflows.bundle_check import check_bundle_references
from lightcycle.domain.work.detail import (
    DetailEntry,
    default_detail,
    detail_presents,
    detail_shape_problem,
    parse_detail,
    resolve_detail,
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
    def test_default_list_adds_pr_with_a_run_and_park_fields_when_parked(self):
        self.assertEqual(default_detail(False, False), ("outcome", "report"))
        self.assertEqual(default_detail(True, False), ("outcome", "report", "pr"))
        self.assertEqual(
            default_detail(True, True), ("outcome", "report", "pr", "needs", "reason"))

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


if __name__ == "__main__":
    unittest.main()
