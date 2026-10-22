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
    return bool(_expected(on_block, changed, base).expected)


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
