import json
import unittest

from lightcycle.domain.flow.flow import Flow
from lightcycle.domain.flow.graph import parse_graph
from lightcycle.domain.schedule.guards import (
    guard_names,
    is_script_guard,
    parse_guard_params,
    script_guard_path,
)
from lightcycle.domain.workflows.lifecycle import parse_lifecycle, workflow_script_env
from lightcycle.domain.workflows.script_stage import (
    fixture_path,
    parse_fixture,
    parse_guard_output,
    parse_script_stage,
    parse_stage_output,
    script_path_problem,
)

OUTCOMES = ("found", "none")


class TestParseStageOutput(unittest.TestCase):
    def test_accepts_the_binding_shape(self):
        out = parse_stage_output(json.dumps({
            "outcome": "found", "artifacts": {"digest": "3 rows"}, "note": "rows"}), OUTCOMES)

        self.assertEqual(
            (out.outcome, out.artifacts, out.note), ("found", {"digest": "3 rows"}, "rows"))

    def test_an_outcome_alone_is_enough(self):
        out = parse_stage_output('{"outcome": "none"}', OUTCOMES)

        self.assertEqual((out.artifacts, out.note), ({}, None))

    def test_rejects_each_violation_on_its_own_input(self):
        bad = {
            "not json": "nope",
            "not an object": "[1]",
            "no outcome": "{}",
            "undeclared outcome": '{"outcome": "other"}',
            "non-string outcome": '{"outcome": 3}',
            "unknown key": '{"outcome": "none", "outcom": "x"}',
            "artifact not a string": '{"outcome": "none", "artifacts": {"a": 1}}',
            "artifacts not an object": '{"outcome": "none", "artifacts": []}',
            "note not a string": '{"outcome": "none", "note": 4}',
        }
        for label, text in bad.items():
            with self.subTest(label):
                with self.assertRaises(ValueError):
                    parse_stage_output(text, OUTCOMES)


class TestParseGuardOutput(unittest.TestCase):
    def test_pass_with_a_title(self):
        out = parse_guard_output(json.dumps({
            "outcome": "pass", "title": "T", "description": "D", "state": "S", "note": "N"}))

        self.assertEqual(
            (out.passed, out.title, out.description, out.state, out.note),
            (True, "T", "D", "S", "N"))

    def test_fail_needs_no_title(self):
        self.assertFalse(parse_guard_output('{"outcome": "fail"}').passed)

    def test_pass_without_a_title_is_a_violation(self):
        for text in ('{"outcome": "pass"}', '{"outcome": "pass", "title": "  "}'):
            with self.subTest(text):
                with self.assertRaises(ValueError):
                    parse_guard_output(text)

    def test_unknown_outcome_and_unknown_key_are_violations(self):
        for text in ('{"outcome": "maybe"}', '{"outcome": "fail", "titel": "x"}', "oops"):
            with self.subTest(text):
                with self.assertRaises(ValueError):
                    parse_guard_output(text)

    def test_a_valid_and_an_invalid_entry_are_judged_separately(self):
        self.assertTrue(parse_guard_output('{"outcome": "pass", "title": "T"}').passed)
        with self.assertRaises(ValueError):
            parse_guard_output('{"outcome": "pass"}')


class TestParseFixture(unittest.TestCase):
    def _text(self, **overrides):
        data = {
            "found": {"outcome": "found", "artifacts": {"digest": "x"}},
            "none": {"outcome": "none"},
        }
        data.update(overrides)
        return json.dumps({k: v for k, v in data.items() if v is not None})

    def test_all_outcomes_present(self):
        parsed = parse_fixture(self._text(), OUTCOMES)

        self.assertEqual(sorted(parsed), ["found", "none"])

    def test_a_missing_outcome_is_named(self):
        with self.assertRaisesRegex(ValueError, "no entry for outcome none"):
            parse_fixture(self._text(none=None), OUTCOMES)

    def test_a_key_that_disagrees_with_its_value_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "names outcome found"):
            parse_fixture(self._text(none={"outcome": "found"}), OUTCOMES)

    def test_a_script_serving_two_stages_may_hold_extra_outcomes(self):
        parsed = parse_fixture(self._text(), ("found",))

        self.assertEqual(sorted(parsed), ["found"])

    def test_a_guard_fixture_needs_pass_and_fail_and_nothing_else(self):
        good = json.dumps({"pass": {"outcome": "pass", "title": "T"}, "fail": {"outcome": "fail"}})
        extra = json.dumps({
            "pass": {"outcome": "pass", "title": "T"}, "fail": {"outcome": "fail"},
            "other": {"outcome": "fail"}})

        self.assertEqual(sorted(parse_fixture(good, (), guard=True)), ["fail", "pass"])
        with self.assertRaises(ValueError):
            parse_fixture(extra, (), guard=True)

    def test_unparseable_fixture_is_rejected(self):
        for text in ("nope", "[]"):
            with self.subTest(text):
                with self.assertRaises(ValueError):
                    parse_fixture(text, OUTCOMES)


class TestPaths(unittest.TestCase):
    def test_fixture_path_mirrors_the_script_path(self):
        self.assertEqual(
            fixture_path("scripts/poll-sheet.py"), "scripts/fixtures/poll-sheet.py.json")

    def test_script_path_rules(self):
        self.assertIsNone(script_path_problem("script", "scripts/a.sh"))
        for path in ("a.sh", "scripts/", "scripts/../a.sh", "/etc/passwd"):
            with self.subTest(path):
                self.assertIsNotNone(script_path_problem("script", path))

    def test_parse_script_stage_reads_the_front_matter(self):
        self.assertEqual(parse_script_stage({"script": " scripts/a.sh "}), "scripts/a.sh")
        self.assertIsNone(parse_script_stage({"model": "sonnet"}))
        self.assertIsNone(parse_script_stage({"script": ""}))


class TestScriptGuardName(unittest.TestCase):
    def test_script_prefix_is_recognised_and_engine_names_are_unchanged(self):
        self.assertTrue(is_script_guard("script:scripts/a.sh"))
        self.assertEqual(script_guard_path("script:scripts/a.sh"), "scripts/a.sh")
        self.assertNotIn("script:scripts/a.sh", guard_names())
        self.assertEqual(
            sorted(guard_names()),
            ["day-unsummarised", "materials-changed", "pending-reflections", "repos-active"])

    def test_params_pass_through_untouched_for_a_script_guard(self):
        self.assertEqual(
            parse_guard_params("script:scripts/a.sh", {"sheet": "abc"}), {"sheet": "abc"})

    def test_a_bad_script_guard_path_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_guard_params("script:../a.sh", {})

    def test_an_unknown_plain_name_is_still_rejected(self):
        with self.assertRaises(ValueError):
            parse_guard_params("scripts/a.sh", {})


class TestStageOwnership(unittest.TestCase):
    def test_a_step_with_script_is_engine_owned(self):
        graph = parse_graph("entry: poll\n\nedges:\n  poll  found  done\n  poll  none  poll\n")
        flow = Flow.from_graph(graph, {"poll": {"script": "scripts/p.sh"}, "done": {}})

        self.assertEqual(flow.step_def("poll").owner, "engine")
        self.assertEqual(flow.step_def("poll").script, "scripts/p.sh")

    def test_script_wins_over_model_for_ownership(self):
        graph = parse_graph("entry: poll\n\nedges:\n  poll  found  done\n")
        flow = Flow.from_graph(graph, {"poll": {"script": "scripts/p.sh", "model": "sonnet"}})

        self.assertEqual(flow.step_def("poll").owner, "engine")


class TestHooklessLifecycle(unittest.TestCase):
    def test_config_without_a_lifecycle_block_gives_a_hookless_lifecycle(self):
        declared = parse_lifecycle({"config": {"api-token": "required"}})

        self.assertEqual(declared.declared_hooks(), ())
        self.assertEqual(declared.required_keys(), ("api-token",))

    def test_none_of_the_three_blocks_gives_none(self):
        self.assertIsNone(parse_lifecycle({"schedule": {"cron": "0 * * * *"}}))

    def test_script_env_has_no_hook_variable_when_no_hook_is_given(self):
        declared = parse_lifecycle({"config": {"api-token": "required"}})

        env = workflow_script_env(
            {}, None, "acme", "build", "/d", "/b", "sha", declared, {"api-token": "t"})

        self.assertNotIn("LC_WORKFLOW_HOOK", env)
        self.assertEqual(env["LC_WORKFLOW_CONFIG_API_TOKEN"], "t")


class TestInRepoLibraryDeclaresNoScripts(unittest.TestCase):
    def test_no_step_or_workflow_in_the_support_library_uses_scripts(self):
        from pathlib import Path

        from lightcycle.frontmatter import split_frontmatter

        library = Path(__file__).resolve().parents[1] / "support" / "library"
        steps = sorted((library / "steps").glob("*.md"))
        workflows = sorted((library / "workflows").glob("*.md"))
        self.assertTrue(steps and workflows)
        for step in steps:
            meta, _ = split_frontmatter(step.read_text())
            self.assertIsNone(parse_script_stage(meta), step.name)
        for workflow in workflows:
            meta, _ = split_frontmatter(workflow.read_text())
            guard = (meta.get("schedule") or {}).get("guard", "")
            self.assertFalse(is_script_guard(guard), workflow.name)
