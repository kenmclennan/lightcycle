import unittest
from pathlib import Path

from lightcycle.domain.pool import pr_workflows_expected
from lightcycle.ports.github import WorkflowFile

_CAPTURED = Path(__file__).resolve().parent.parent / "support" / "captured_workflows"


def _expected(on_block, changed=("a.py",), base="main"):
    result = pr_workflows_expected(
        (WorkflowFile("w.yml", "name: w\n" + on_block + "jobs:\n  b:\n    runs-on: x\n"),),
        base, frozenset(changed))
    return result


def _runs(on_block, changed=("a.py",), base="main"):
    result = _expected(on_block, changed, base)
    assert result.unreadable == (), on_block
    return bool(result.expected)


def _unreadable(on_block, changed=("a.py",), base="main"):
    result = _expected(on_block, changed, base)
    return result.unreadable == ("w.yml",) and result.expected == ("w.yml",)


class TestEventSelection(unittest.TestCase):
    def test_push_only_block_is_not_expected(self):
        self.assertFalse(_runs("on:\n  push:\n    branches: [main]\n"))

    def test_push_only_block_list_form_is_not_expected(self):
        self.assertFalse(_runs("on:\n  push:\n    branches:\n      - main\n"))

    def test_schedule_only_is_not_expected(self):
        self.assertFalse(_runs("on:\n  schedule:\n    - cron: '0 0 * * *'\n"))

    def test_workflow_dispatch_only_is_not_expected(self):
        self.assertFalse(_runs("on: [workflow_dispatch]\n"))

    def test_push_and_bare_pull_request_is_expected(self):
        self.assertTrue(_runs("on:\n  push:\n  pull_request:\n"))

    def test_pull_request_target_is_expected(self):
        self.assertTrue(_runs("on:\n  pull_request_target:\n"))

    def test_scalar_form(self):
        self.assertTrue(_runs("on: pull_request\n"))
        self.assertFalse(_runs("on: push\n"))

    def test_flow_list_form(self):
        self.assertTrue(_runs("on: [push, pull_request]\n"))

    def test_block_list_form(self):
        self.assertTrue(_runs("on:\n  - push\n  - pull_request\n"))
        self.assertTrue(_runs("on:\n- push\n- pull_request\n"))

    def test_quoted_and_boolean_on_keys(self):
        self.assertTrue(_runs('"on":\n  pull_request:\n'))
        self.assertTrue(_runs("'on':\n  pull_request:\n"))
        self.assertTrue(_runs("true:\n  pull_request:\n"))

    def test_comments_are_stripped(self):
        self.assertTrue(_runs("on:  # triggers\n  # push:\n  pull_request:  # prs\n"))
        self.assertFalse(_runs("on:\n  push:\n  # pull_request:\n"))


class TestBranchFilters(unittest.TestCase):
    def test_branches_excluding_the_base_is_not_expected(self):
        self.assertFalse(_runs("on:\n  pull_request:\n    branches: ['release/**']\n"))

    def test_branches_admitting_the_base_is_expected(self):
        self.assertTrue(_runs("on:\n  pull_request:\n    branches: ['release/**']\n", base="release/1.2"))

    def test_branches_ignore_the_base_is_not_expected(self):
        self.assertFalse(_runs("on:\n  pull_request:\n    branches-ignore: [main]\n"))


class TestPathFilters(unittest.TestCase):
    def test_paths_that_every_changed_file_misses(self):
        block = "on:\n  pull_request:\n    paths: ['src/**']\n"
        self.assertFalse(_runs(block, ("docs/a.md", "README.md")))

    def test_paths_that_one_changed_file_hits(self):
        block = "on:\n  pull_request:\n    paths: ['src/**']\n"
        self.assertTrue(_runs(block, ("docs/a.md", "src/x/y.py")))

    def test_paths_ignore_matching_every_changed_file(self):
        block = "on:\n  pull_request:\n    paths-ignore: ['docs/**', '*.md']\n"
        self.assertFalse(_runs(block, ("docs/a.md", "README.md")))

    def test_paths_ignore_leaving_one_file_unmatched(self):
        block = "on:\n  pull_request:\n    paths-ignore: ['docs/**']\n"
        self.assertTrue(_runs(block, ("docs/a.md", "b.py")))

    def test_star_does_not_cross_a_slash_and_double_star_does(self):
        self.assertFalse(_runs("on:\n  pull_request:\n    paths: ['*.py']\n", ("src/a.py",)))
        self.assertTrue(_runs("on:\n  pull_request:\n    paths: ['**/*.py']\n", ("src/a.py",)))
        self.assertTrue(_runs("on:\n  pull_request:\n    paths: ['**/*.py']\n", ("a.py",)))

    def test_negation_is_evaluated_in_order(self):
        block = "on:\n  pull_request:\n    paths:\n      - 'src/**'\n      - '!src/gen/**'\n"
        self.assertFalse(_runs(block, ("src/gen/x.py",)))
        self.assertTrue(_runs(block, ("src/x.py",)))
        reordered = "on:\n  pull_request:\n    paths:\n      - '!src/gen/**'\n      - 'src/**'\n"
        self.assertTrue(_runs(reordered, ("src/gen/x.py",)))

    def test_299_changed_files_are_evaluated_and_300_admit(self):
        block = "on:\n  pull_request:\n    paths: ['src/**']\n"
        self.assertFalse(_runs(block, ["docs/%d.md" % i for i in range(299)]))
        self.assertTrue(_runs(block, ["docs/%d.md" % i for i in range(300)]))


class TestDoubtResolvesToShouldRun(unittest.TestCase):
    def test_flow_mapping_is_unparseable_and_expected(self):
        result = _expected("on: {pull_request: {branches: [main]}}\n", base="dev")
        self.assertEqual(result.expected, ("w.yml",))
        self.assertEqual(result.unreadable, ("w.yml",))

    def test_unsupported_glob_is_expected_and_listed(self):
        result = _expected("on:\n  pull_request:\n    paths: ['a?.py']\n", ("z.py",))
        self.assertEqual(result.expected, ("w.yml",))
        self.assertEqual(result.unreadable, ("w.yml",))

    def test_missing_on_is_expected_and_listed(self):
        result = pr_workflows_expected((WorkflowFile("w.yml", "name: w\njobs: {}\n"),), "main", frozenset({"a.py"}))
        self.assertEqual(result.expected, ("w.yml",))
        self.assertEqual(result.unreadable, ("w.yml",))

    def test_unreadable_file_is_expected_and_listed(self):
        result = pr_workflows_expected((WorkflowFile("w.yml", None),), "main", frozenset({"a.py"}))
        self.assertEqual(result.expected, ("w.yml",))
        self.assertEqual(result.unreadable, ("w.yml",))

    def test_duplicate_on_and_tabs_and_anchors_are_unparseable(self):
        for text in (
            "on: push\non: pull_request\n",
            "on:\n\tpull_request:\n",
            "on:\n  pull_request:\n    branches: *main\n",
            "on:\n  pull_request:\n    branches: |\n      main\n",
        ):
            result = pr_workflows_expected((WorkflowFile("w.yml", text),), "main", frozenset({"a.py"}))
            self.assertEqual(result.unreadable, ("w.yml",), text)

    def test_a_clean_file_is_not_listed_as_unreadable(self):
        self.assertEqual(_expected("on: pull_request\n").unreadable, ())


class TestParserEdges(unittest.TestCase):
    def test_hash_inside_a_quote_is_not_a_comment(self):
        block = "on:\n  pull_request:\n    branches: ['a # b']  # why\n"
        self.assertTrue(_runs(block, base="a # b"))

    def test_hash_glued_to_text_is_not_a_comment(self):
        self.assertTrue(_runs("on:\n  pull_request:\n    branches: [a#b]\n", base="a#b"))

    def test_unindented_comment_line_does_not_end_the_on_block(self):
        self.assertTrue(_runs("on:\n  push:\n# note\n  pull_request:\n"))

    def test_unquoted_letter_x_is_not_a_quote(self):
        self.assertTrue(_runs("on:\n  pull_request:\n    branches: [X]  # c\n", base="X"))
        self.assertTrue(_runs("on:\n  pull_request:\n    branches:\n      - Xa\n", base="Xa"))

    def test_quote_in_the_middle_of_a_flow_item_is_kept(self):
        block = "on:\n  pull_request:\n    branches: [a'b']\n"
        self.assertTrue(_runs(block, base="a'b'"))
        self.assertFalse(_runs(block, base="b"))

    def test_comma_inside_a_quoted_flow_item_does_not_split(self):
        block = "on:\n  pull_request:\n    branches: ['x,y']\n"
        self.assertTrue(_runs(block, base="x,y"))
        self.assertFalse(_runs(block, base="x"))

    def test_empty_quoted_scalar_is_readable(self):
        self.assertFalse(_runs('on: ""\n'))
        self.assertFalse(_runs("on: ''\n"))

    def test_lone_quote_is_unreadable(self):
        self.assertTrue(_unreadable('on: "\n'))

    def test_scalars_starting_with_yaml_syntax_are_unreadable(self):
        for lead in "&*|>{[!%@`":
            self.assertTrue(_unreadable("on:\n  - %sx\n" % lead), lead)

    def test_scalar_with_colon_space_or_trailing_colon_is_unreadable(self):
        self.assertTrue(_unreadable("on:\n  - a: b\n"))
        self.assertTrue(_unreadable("on:\n  - a:\n"))

    def test_unterminated_flow_list_is_unreadable(self):
        self.assertTrue(_unreadable("on: [push, pull_request\n"))

    def test_nested_flow_collection_is_unreadable(self):
        self.assertTrue(_unreadable("on: [push, [pull_request]]\n"))
        self.assertTrue(_unreadable("on: [push, {a: b}]\n"))

    def test_empty_flow_list_is_readable_and_expects_nothing(self):
        self.assertFalse(_runs("on: []\n"))

    def test_empty_flow_item_is_unreadable(self):
        self.assertTrue(_unreadable("on: [push, ]\n"))

    def test_list_under_a_filter_key_may_sit_at_the_key_indent(self):
        block = "on:\n  pull_request:\n    paths:\n    - 'src/**'\n"
        self.assertTrue(_runs(block, ("src/a.py",)))
        self.assertFalse(_runs(block, ("docs/a.md",)))

    def test_key_containing_a_colon_in_its_value_splits_at_the_first_colon(self):
        block = "on:\n  pull_request:\n    branches: ['x:y']\n"
        self.assertTrue(_runs(block, base="x:y"))
        self.assertFalse(_runs(block, base="other"))

    def test_quoted_event_key_is_unquoted(self):
        self.assertTrue(_runs("on:\n  'pull_request':\n"))
        self.assertTrue(_runs('on:\n  "pull_request":\n'))

    def test_empty_key_is_readable(self):
        self.assertFalse(_runs("on:\n  : x\n"))

    def test_null_and_tilde_event_values_are_bare_events(self):
        self.assertTrue(_runs("on:\n  pull_request: null\n"))
        self.assertTrue(_runs("on:\n  pull_request: ~\n"))

    def test_scalar_event_value_for_a_pr_event_is_unreadable(self):
        self.assertTrue(_unreadable("on:\n  pull_request: foo\n"))

    def test_event_children_must_share_one_indent(self):
        self.assertTrue(_unreadable("on:\n  pull_request:\n      branches: [a]\n    paths: [b]\n"))

    def test_two_filter_keys_in_one_event_are_both_honoured(self):
        block = "on:\n  pull_request:\n    branches: [main]\n    paths: ['src/**']\n"
        self.assertTrue(_runs(block, ("src/a.py",)))
        self.assertFalse(_runs(block, ("docs/a.md",)))

    def test_duplicate_filter_key_is_unreadable(self):
        block = "on:\n  pull_request:\n    paths: [a]\n    paths: [b]\n"
        self.assertTrue(_unreadable(block))

    def test_tab_inside_the_on_body_is_unreadable(self):
        self.assertTrue(_unreadable("on:\n  pull_request:\n  \tbranches: [main]\n"))

    def test_tab_on_the_on_line_is_unreadable(self):
        self.assertTrue(_unreadable("on:\tpull_request\n"))

    def test_yaml_syntax_values_on_a_non_pr_event_are_unreadable(self):
        for lead in "&*|>":
            self.assertTrue(_unreadable("on:\n  push: %sx\n" % lead), lead)

    def test_comment_marker_needs_whitespace_before_it_and_none_after(self):
        self.assertTrue(_runs("on: pull_request #c\n"))
        self.assertTrue(_runs("on:\n  pull_request:  #\n"))

    def test_hash_after_the_letter_x_is_not_a_comment(self):
        self.assertTrue(_runs("on:\n  pull_request:\n    branches: [aX#b]\n", base="aX#b"))

    def test_on_body_lines_must_share_one_indent(self):
        self.assertTrue(_unreadable("on:\n    pull_request:\n  push:\n"))

    def test_list_item_as_the_first_event_child_is_unreadable(self):
        self.assertTrue(_unreadable("on:\n  pull_request:\n    - a: b\n"))

    def test_double_star_slash_matches_nested_directories_and_keeps_the_prefix(self):
        block = "on:\n  pull_request:\n    paths: ['src/**/x.py']\n"
        self.assertTrue(_runs(block, ("src/a/b/x.py",)))
        self.assertTrue(_runs(block, ("src/x.py",)))
        self.assertFalse(_runs(block, ("other/x.py",)))

    def test_double_star_without_a_slash_consumes_exactly_two_characters(self):
        self.assertFalse(_runs("on:\n  pull_request:\n    paths: ['**.md']\n", ("xmd",)))
        self.assertTrue(_runs("on:\n  pull_request:\n    paths: ['**.md']\n", ("a/b.md",)))

    def test_single_star_consumes_exactly_one_character(self):
        self.assertFalse(_runs("on:\n  pull_request:\n    paths: ['*.py']\n", ("apy",)))
        self.assertTrue(_runs("on:\n  pull_request:\n    paths: ['*.py']\n", ("a.py",)))

    def test_unsupported_globs_are_checked_even_when_path_evaluation_is_skipped(self):
        many = ["docs/%d.md" % i for i in range(300)]
        for key in ("paths", "paths-ignore"):
            for pattern in ("a?.py", "!a?.py", "?x", "!?x"):
                block = "on:\n  pull_request:\n    %s: ['%s']\n" % (key, pattern)
                self.assertTrue(_unreadable(block, many), (key, pattern))

    def test_supported_negated_glob_is_not_unreadable_when_path_evaluation_is_skipped(self):
        many = ["docs/%d.md" % i for i in range(300)]
        block = "on:\n  pull_request:\n    paths: ['src/**', '!src/gen/**']\n"
        self.assertTrue(_runs(block, many))


class TestWorkflowListHandling(unittest.TestCase):
    OK = "name: ok\non: pull_request\n"

    def test_a_missing_text_does_not_stop_the_scan(self):
        result = pr_workflows_expected(
            (WorkflowFile("a.yml", None), WorkflowFile("b.yml", self.OK)), "main", frozenset({"x"}))
        self.assertEqual(result.expected, ("a.yml", "b.yml"))
        self.assertEqual(result.unreadable, ("a.yml",))

    def test_an_unparseable_text_does_not_stop_the_scan(self):
        result = pr_workflows_expected(
            (WorkflowFile("a.yml", "name: a\n"), WorkflowFile("b.yml", self.OK)), "main", frozenset({"x"}))
        self.assertEqual(result.expected, ("a.yml", "b.yml"))
        self.assertEqual(result.unreadable, ("a.yml",))

    def test_a_workflow_that_does_not_run_does_not_stop_the_scan(self):
        result = pr_workflows_expected(
            (WorkflowFile("a.yml", "on: push\n"), WorkflowFile("b.yml", self.OK)), "main", frozenset({"x"}))
        self.assertEqual(result.expected, ("b.yml",))


class TestCapturedWorkflows(unittest.TestCase):
    def _files(self):
        return tuple(
            WorkflowFile(p.name, p.read_text()) for p in sorted(_CAPTURED.glob("*.yml")))

    def test_only_the_pull_request_workflow_is_expected(self):
        for changed in ({"lightcycle/x.py"}, {"docs/a.md"}):
            result = pr_workflows_expected(self._files(), "main", frozenset(changed))
            self.assertEqual(result.expected, ("ci.yml",))
            self.assertEqual(result.unreadable, ())


if __name__ == "__main__":
    unittest.main()
