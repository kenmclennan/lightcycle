import os
import shutil
import tempfile
import unittest

from lightcycle.adapters.fsio import FsAdapter
from lightcycle.adapters.workflow_bundle import WorkflowBundleAdapter
from lightcycle.application.workflows.check_dir import CheckWorkflowDirUseCase
from lightcycle.application.workflows.script_tooling import WorkflowScripts
from tests.support.script_bundle import GUARD_FIXTURE, STAGE_FIXTURE, write_script_bundle


class _Config:
    def prompts_root(self):
        return "/nonexistent"

    def data_root(self):
        return "/nonexistent-data-root"


class CheckTestCase(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.root, ignore_errors=True))
        self.fs = FsAdapter(_Config())
        self.bundle = WorkflowBundleAdapter()

    def problems(self, **kwargs):
        shutil.rmtree(self.root, ignore_errors=True)
        write_script_bundle(self.root, **kwargs)
        return WorkflowScripts(self.bundle, self.fs).problems(self.root, "build")

    def assertOneProblem(self, found, *needles):
        self.assertEqual(len(found), 1, found)
        for needle in needles:
            self.assertIn(needle, found[0])


class TestScriptChecks(CheckTestCase):
    def test_a_good_bundle_has_no_problem(self):
        self.assertEqual(self.problems(), [])

    def test_a_bundle_with_no_scripts_gains_no_problem(self):
        self.assertEqual(self.problems(stage_script=None, guard=False, stage_fixture=None), [])

    def test_a_script_path_outside_scripts_is_a_problem(self):
        self.assertOneProblem(
            self.problems(stage_script="bin/poll.sh", stage_fixture=None), "under scripts/")

    def test_a_script_path_with_dotdot_is_a_problem(self):
        self.assertOneProblem(
            self.problems(stage_script="scripts/../poll.sh", stage_fixture=None), "'..'")

    def test_a_missing_script_is_a_problem(self):
        self.assertOneProblem(self.problems(poll_sh=None), "does not exist")

    def test_a_non_executable_script_is_a_problem(self):
        self.assertOneProblem(self.problems(poll_executable=False), "not executable")

    def test_a_script_with_a_model_is_a_problem(self):
        self.assertOneProblem(self.problems(step_extra="model: sonnet"), "two owners")

    def test_a_script_stage_with_a_ci_hook_is_a_problem(self):
        write_script_bundle(self.root)
        path = os.path.join(self.root, "workflows", "build.md")
        with open(path) as f:
            text = f.read()
        text = text.replace("display:", "hooks:\n  ci_success  poll  found\n\ndisplay:")
        with open(path, "w") as f:
            f.write(text)

        found = WorkflowScripts(self.bundle, self.fs).problems(self.root, "build")

        self.assertOneProblem(found, "ci_success")

    def test_a_script_stage_with_no_outcome_is_a_problem(self):
        write_script_bundle(self.root)
        path = os.path.join(self.root, "workflows", "build.md")
        with open(path) as f:
            text = f.read()
        text = text.replace("  poll  found  finish\n  poll  none   idle\n", "  finish  done  idle\n")
        with open(path, "w") as f:
            f.write(text)

        found = WorkflowScripts(self.bundle, self.fs).problems(self.root, "build")

        self.assertTrue(any("declares no outcome" in p for p in found), found)

    def test_a_missing_fixture_is_a_problem(self):
        self.assertOneProblem(self.problems(stage_fixture=None), "fixtures/poll.sh.json")

    def test_an_incomplete_fixture_is_a_problem(self):
        partial = {"found": STAGE_FIXTURE["found"]}
        self.assertOneProblem(
            self.problems(stage_fixture=partial), "no entry for outcome none")

    def test_an_unparseable_fixture_is_a_problem(self):
        self.assertOneProblem(self.problems(stage_fixture="x"), "")

    def test_guard_path_existence_executability_and_fixture_are_checked(self):
        self.assertOneProblem(self.problems(changed_sh=None), "script guard", "does not exist")
        self.assertOneProblem(self.problems(guard_fixture=None), "script guard", "fixture")
        self.assertOneProblem(
            self.problems(guard_fixture={"pass": GUARD_FIXTURE["pass"]}), "script guard", "fail")

    def test_files_under_fixtures_and_tests_are_not_scripts(self):
        write_script_bundle(self.root)
        with open(os.path.join(self.root, "scripts", "fixtures", "extra.txt"), "w") as f:
            f.write("x")
        os.makedirs(os.path.join(self.root, "scripts", "tests"))
        with open(os.path.join(self.root, "scripts", "tests", "test_poll.sh"), "w") as f:
            f.write("x")

        self.assertEqual(WorkflowScripts(self.bundle, self.fs).problems(self.root, "build"), [])


class TestRequiresEngine(CheckTestCase):
    def _check(self, **kwargs):
        write_script_bundle(self.root, **kwargs)
        return CheckWorkflowDirUseCase(self.bundle, self.fs, "0.6.332").execute(self.root, None)

    def test_a_bundle_using_scripts_without_requires_engine_is_reported(self):
        resp = self._check(requires_engine=False)

        messages = [m for ms in resp.lifecycle_problems.values() for m in ms]
        self.assertTrue(any("requires-engine" in m for m in messages), messages)

    def test_with_requires_engine_nothing_about_it_is_reported(self):
        resp = self._check()

        messages = [m for ms in resp.lifecycle_problems.values() for m in ms]
        self.assertEqual(messages, [])
