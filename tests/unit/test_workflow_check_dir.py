import copy
import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from lightcycle import cli
from lightcycle.adapters.fsio import FsAdapter
from lightcycle.adapters.workflow_bundle import WorkflowBundleAdapter
from lightcycle.domain.work import worker_permitted
from lightcycle.render import worker_refusal_message
from lightcycle.domain.workflows.contract import ENGINE_CONTRACT
from tests.support.fake_store import FakeStore
from tests.support.script_bundle import write_script_bundle

LIBRARY = Path(__file__).resolve().parents[1] / "support" / "library"
ENGINE_PROMPTS = Path(cli.__file__).resolve().parent / "prompts"


class _Config:
    def prompts_root(self):
        return str(ENGINE_PROMPTS)

    def workflow_retention(self):
        return 5

    def version(self):
        return "0.6.319"

    def data_root(self):
        return "/nonexistent-data-root"


class _Container:
    def __init__(self):
        self.store = FakeStore()
        self.config = _Config()
        self.fs = FsAdapter(self.config)
        self.workflow_bundle = WorkflowBundleAdapter()
        self.workflow_source = None


def _bundle(root, name="spec-driven"):
    shutil.copytree(LIBRARY / "steps", os.path.join(root, "steps"))
    for entry in os.scandir(os.path.join(root, "steps")):
        with open(entry.path) as f:
            text = f.read()
        head = text.split("---")[1] if text.startswith("---") else ""
        with open(entry.path, "w") as f:
            f.write("---%s---\nDo the step.\n" % head)
    os.makedirs(os.path.join(root, "workflows"))
    shutil.copy(LIBRARY / "workflows" / "spec-driven.md", os.path.join(root, "workflows", name + ".md"))
    with open(os.path.join(root, "source.toml"), "w") as f:
        f.write('name = "t"\ncontract = %d\n' % ENGINE_CONTRACT)
    return root


def _break(root):
    with open(os.path.join(root, "steps", "cleanup.md"), "a") as f:
        f.write("\n@include nonexistent-frag\n")


def run_check(*args):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = cli.cmd_workflow(["check", *args])
    return rc, out.getvalue(), err.getvalue()


_LIFECYCLE_FRONT = (
    "---\nlifecycle:\n  install: scripts/install.sh\n  maintain: scripts/maintain.sh\n"
    "  cron: 0 3 * * *\nconfig:\n  api-token: required\nconfig-example:\n  api-token: x\n---\n")


class TestWorkflowCheckDirLifecycle(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        cli.set_container(_Container())
        self.root = _bundle(self.tmp)
        path = os.path.join(self.root, "workflows", "spec-driven.md")
        with open(path) as f:
            body = f.read()
        with open(path, "w") as f:
            f.write(_LIFECYCLE_FRONT + body)
        with open(os.path.join(self.root, "source.toml"), "a") as f:
            f.write('requires-engine = ">=0.6.318"\n')
        os.makedirs(os.path.join(self.root, "scripts"))
        for name in ("install.sh", "maintain.sh"):
            script = os.path.join(self.root, "scripts", name)
            with open(script, "w") as f:
                f.write("#!/bin/sh\n")
            os.chmod(script, 0o755)

    def test_a_sound_lifecycle_passes(self):
        rc, _out, err = run_check("--dir", self.root, "spec-driven")
        self.assertEqual(rc, 0, err)

    def test_a_missing_script_is_listed(self):
        os.remove(os.path.join(self.root, "scripts", "maintain.sh"))
        rc, _out, err = run_check("--dir", self.root, "spec-driven")
        self.assertEqual(rc, 1)
        self.assertIn("lifecycle maintain script scripts/maintain.sh does not exist", err)

    def test_a_non_executable_script_is_listed(self):
        os.chmod(os.path.join(self.root, "scripts", "install.sh"), 0o644)
        rc, _out, err = run_check("--dir", self.root, "spec-driven")
        self.assertEqual(rc, 1)
        self.assertIn("scripts/install.sh is not executable", err)

    def test_a_lifecycle_without_requires_engine_is_listed(self):
        with open(os.path.join(self.root, "source.toml"), "w") as f:
            f.write('name = "t"\ncontract = %d\n' % ENGINE_CONTRACT)
        rc, _out, err = run_check("--dir", self.root, "spec-driven")
        self.assertEqual(rc, 1)
        self.assertIn("declares lifecycle: but source.toml has no requires-engine", err)

    def test_a_bundle_without_a_lifecycle_gains_no_problem(self):
        other = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, other, ignore_errors=True)
        rc, _out, err = run_check("--dir", _bundle(other), "spec-driven")
        self.assertEqual(rc, 0, err)


class TestWorkflowCheckDir(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.container = _Container()
        cli.set_container(self.container)

    def test_valid_bundle_passes(self):
        rc, _out, err = run_check("--dir", _bundle(self.tmp), "spec-driven")
        self.assertEqual(rc, 0, err)

    def _require(self, requirement):
        root = _bundle(self.tmp)
        with open(os.path.join(root, "source.toml"), "a") as f:
            f.write('requires-engine = "%s"\n' % requirement)
        return root

    def test_unmet_engine_requirement_is_listed_among_the_problems(self):
        rc, _out, err = run_check("--dir", self._require(">=0.7.0"), "spec-driven")
        self.assertNotEqual(rc, 0)
        self.assertIn(">=0.7.0", err)
        self.assertIn("0.6.319", err)

    def test_met_engine_requirement_passes(self):
        rc, _out, err = run_check("--dir", self._require(">=0.6.318,<0.7.0"), "spec-driven")
        self.assertEqual(rc, 0, err)

    def test_missing_fragment_fails_with_the_not_found_message(self):
        _bundle(self.tmp)
        _break(self.tmp)
        rc, _out, err = run_check("--dir", self.tmp, "spec-driven")
        self.assertEqual(rc, 1)
        self.assertIn("fragment 'nonexistent-frag' included by steps/cleanup.md not found", err)

    def _set_step(self, body, role="cleanup"):
        _bundle(self.tmp)
        path = os.path.join(self.tmp, "steps", "%s.md" % role)
        with open(path) as f:
            text = f.read()
        head = text.split("---")[1]
        with open(path, "w") as f:
            f.write("---%s---\n%s" % (head, body))

    def test_restarted_list_fails_naming_file_and_line(self):
        self._set_step("1. a\n2. b\n\n1. c\n")
        rc, _out, err = run_check("--dir", self.tmp, "spec-driven")
        self.assertEqual(rc, 1)
        self.assertIn("steps/cleanup.md line 5: top-level list item 1 follows 2", err)

    def test_indented_include_fails_naming_file_and_line(self):
        self._set_step("Do it.\n  @include plain-language\n")
        rc, _out, err = run_check("--dir", self.tmp, "spec-driven")
        self.assertEqual(rc, 1)
        self.assertIn("steps/cleanup.md line 3: @include plain-language is indented", err)

    def test_unresolvable_include_fails_naming_file_and_line(self):
        self._set_step("Do it.\n\n@include nonexistent-frag\n")
        rc, _out, err = run_check("--dir", self.tmp, "spec-driven")
        self.assertEqual(rc, 1)
        self.assertIn("steps/cleanup.md line 4: @include nonexistent-frag does not resolve", err)

    def test_sound_include_and_nested_list_pass(self):
        self._set_step("1. a\n  1. nested\n2. b\n\n@include plain-language\n")
        rc, _out, err = run_check("--dir", self.tmp, "spec-driven")
        self.assertEqual(rc, 0, err)

    def _add_fragment(self, name):
        os.makedirs(os.path.join(self.tmp, "fragments"), exist_ok=True)
        with open(os.path.join(self.tmp, "fragments", "%s.md" % name), "w") as f:
            f.write("local\n")

    def test_origin_fragment_resolves(self):
        self._set_step("Do it.\n\n@include x\n")
        self._add_fragment("x")
        rc, _out, err = run_check("--dir", self.tmp, "spec-driven")
        self.assertEqual(rc, 0, err)

    def test_include_in_neither_place_names_both_sources(self):
        self._set_step("Do it.\n@include y\n")
        self._add_fragment("x")
        rc, _out, err = run_check("--dir", self.tmp, "spec-driven")
        self.assertEqual(rc, 1)
        self.assertIn("@include y does not resolve in a pinned bundle", err)
        self.assertIn("available fragments: plain-language, x", err)

    def test_mixed_includes_report_only_the_missing_one(self):
        self._set_step("Do it.\n\n@include x\n@include y\n")
        self._add_fragment("x")
        rc, _out, err = run_check("--dir", self.tmp, "spec-driven")
        self.assertEqual(rc, 1)
        self.assertIn("@include y does not resolve", err)
        self.assertNotIn("@include x does not resolve", err)

    def test_missing_source_toml_refuses_naming_it(self):
        _bundle(self.tmp)
        os.remove(os.path.join(self.tmp, "source.toml"))
        rc, _out, err = run_check("--dir", self.tmp, "spec-driven")
        self.assertEqual(rc, 1)
        self.assertIn("source.toml", err)

    def test_missing_workflows_dir_refuses_naming_it(self):
        _bundle(self.tmp)
        shutil.rmtree(os.path.join(self.tmp, "workflows"))
        rc, _out, err = run_check("--dir", self.tmp)
        self.assertEqual(rc, 1)
        self.assertIn("workflows", err)

    def test_qualified_name_with_dir_refuses(self):
        rc, _out, err = run_check("--dir", _bundle(self.tmp), "origin/spec-driven")
        self.assertEqual(rc, 1)
        self.assertIn("bare name", err)

    def test_neither_workflow_nor_dir_refuses(self):
        rc, _out, err = run_check()
        self.assertEqual(rc, 1)
        self.assertIn("--dir", err)

    def test_omitting_the_name_checks_every_workflow_and_reports_the_failing_one(self):
        _bundle(self.tmp)
        shutil.copy(
            os.path.join(self.tmp, "workflows", "spec-driven.md"),
            os.path.join(self.tmp, "workflows", "broken.md"),
        )
        with open(os.path.join(self.tmp, "workflows", "broken.md"), "a") as f:
            f.write("\nnodes:\n  ghost-node  no-such-step-file\n")
        rc, out, err = run_check("--dir", self.tmp)
        self.assertEqual(rc, 1, err)
        self.assertIn("spec-driven: ok", out)
        self.assertIn("broken: FAILED", out)

    def test_omitting_the_name_passes_when_every_workflow_is_valid(self):
        rc, out, err = run_check("--dir", _bundle(self.tmp))
        self.assertEqual(rc, 0, err)
        self.assertNotIn("FAILED", out)

    def test_json_for_one_workflow_keeps_the_pinned_shape(self):
        rc, out, _err = run_check("--dir", _bundle(self.tmp), "spec-driven", "--json")
        self.assertEqual(rc, 0)
        self.assertIn("owner", json.loads(out))

    def test_json_for_several_workflows_is_keyed_by_name(self):
        _bundle(self.tmp)
        shutil.copy(
            os.path.join(self.tmp, "workflows", "spec-driven.md"),
            os.path.join(self.tmp, "workflows", "other.md"),
        )
        rc, out, _err = run_check("--dir", self.tmp, "--json")
        self.assertEqual(rc, 0)
        self.assertEqual(sorted(json.loads(out)), ["other", "spec-driven"])

    def test_writes_nothing_to_the_store(self):
        _bundle(self.tmp)
        before = copy.deepcopy(vars(self.container.store))
        run_check("--dir", self.tmp, "spec-driven")
        self.assertEqual(vars(self.container.store), before)


class TestWorkerMayCheckDir(unittest.TestCase):
    def test_only_check_with_dir_is_permitted(self):
        self.assertTrue(worker_permitted("workflow", cli._workflow_flags(["check", "--dir", "."])))
        self.assertTrue(worker_permitted(
            "workflow", cli._workflow_flags(["check", "spec-driven", "--dir", "."])))

    def test_every_other_workflow_form_is_refused(self):
        for args in (
            ["check", "o/spec-driven"], ["add", "url"], ["upgrade"], ["rm", "o"],
            ["init", "n"], ["describe", "o/n"], ["simulate", "o/n"], [],
        ):
            self.assertFalse(worker_permitted("workflow", cli._workflow_flags(args)), args)

    def test_workflow_list_is_permitted(self):
        self.assertTrue(worker_permitted("workflow", cli._workflow_flags(["list"])))

    def test_unparseable_workflow_args_are_refused(self):
        with redirect_stderr(io.StringIO()):
            flags = cli._workflow_flags(["bogus"])
        self.assertFalse(worker_permitted("workflow", flags))

    def test_refusal_message_names_the_permitted_form(self):
        self.assertIn("workflow check --dir", worker_refusal_message("rm"))


if __name__ == "__main__":
    unittest.main()


class TestScheduleNeedsRequiresEngine(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        cli.set_container(_Container())

    def _build(self, schedule, requires):
        root = _bundle(self.tmp)
        wf = os.path.join(root, "workflows", "spec-driven.md")
        if schedule:
            with open(wf) as f:
                text = f.read()
            with open(wf, "w") as f:
                f.write("---\nschedule:\n  cron: 0 9 * * 1\n  guard: materials-changed\n---\n" + text)
        if requires:
            with open(os.path.join(root, "source.toml"), "a") as f:
                f.write('requires-engine = ">=0.6.0"\n')
        return root

    def test_a_schedule_without_requires_engine_is_reported(self):
        rc, _out, err = run_check("--dir", self._build(True, False), "spec-driven")
        self.assertEqual(rc, 1)
        self.assertIn(
            "workflow spec-driven declares schedule: but source.toml has no requires-engine; "
            "older engines would ignore it", err)

    def test_a_schedule_with_requires_engine_reports_nothing(self):
        rc, _out, err = run_check("--dir", self._build(True, True), "spec-driven")
        self.assertEqual(rc, 0, err)

    def test_no_schedule_and_no_requires_engine_reports_nothing(self):
        rc, _out, err = run_check("--dir", self._build(False, False), "spec-driven")
        self.assertEqual(rc, 0, err)

    def test_requires_engine_without_a_schedule_reports_nothing(self):
        rc, _out, err = run_check("--dir", self._build(False, True), "spec-driven")
        self.assertEqual(rc, 0, err)


class TestGithubKeyChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        cli.set_container(_Container())

    def _build(self, value, requires):
        root = _bundle(self.tmp)
        step = os.path.join(root, "steps", "write-code.md")
        with open(step) as f:
            text = f.read()
        with open(step, "w") as f:
            f.write(text.replace("---\n", "---\ngithub: %s\n" % value, 1))
        if requires:
            with open(os.path.join(root, "source.toml"), "a") as f:
                f.write('requires-engine = ">=0.6.0"\n')
        return root

    def test_heavy_with_requires_engine_reports_nothing(self):
        rc, _out, err = run_check("--dir", self._build("heavy", True), "spec-driven")
        self.assertEqual(rc, 0, err)

    def test_any_other_value_is_reported(self):
        rc, _out, err = run_check("--dir", self._build("heavey", True), "spec-driven")
        self.assertEqual(rc, 1)
        self.assertIn("declares github: 'heavey'; the only accepted value is heavy", err)

    def test_the_key_without_requires_engine_is_reported(self):
        rc, _out, err = run_check("--dir", self._build("heavy", False), "spec-driven")
        self.assertEqual(rc, 1)
        self.assertIn("declares github: but source.toml has no requires-engine", err)

    def test_the_support_library_bundle_has_no_github_key(self):
        rc, _out, err = run_check("--dir", _bundle(self.tmp), "spec-driven")
        self.assertEqual(rc, 0, err)


class TestAlwaysRunKeyChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        cli.set_container(_Container())

    def _build(self, value, requires):
        root = _bundle(self.tmp)
        step = os.path.join(root, "steps", "write-code.md")
        with open(step) as f:
            text = f.read()
        with open(step, "w") as f:
            f.write(text.replace("---\n", "---\nalways-run: %s\n" % value, 1))
        if requires:
            with open(os.path.join(root, "source.toml"), "a") as f:
                f.write('requires-engine = ">=0.6.0"\n')
        return root

    def test_true_with_requires_engine_reports_nothing(self):
        rc, _out, err = run_check("--dir", self._build("true", True), "spec-driven")
        self.assertEqual(rc, 0, err)

    def test_any_other_value_is_reported(self):
        rc, _out, err = run_check("--dir", self._build("yes", True), "spec-driven")
        self.assertEqual(rc, 1)
        self.assertIn("declares always-run: 'yes'; the only accepted value is true", err)

    def test_the_key_without_requires_engine_is_reported(self):
        rc, _out, err = run_check("--dir", self._build("true", False), "spec-driven")
        self.assertEqual(rc, 1)
        self.assertIn("declares always-run: but source.toml has no requires-engine", err)


class TestOutcomeMarkerKeyChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self._count = iter(range(100))
        cli.set_container(_Container())

    def _build(self, step_file, line, requires=True):
        root = _bundle(os.path.join(self.tmp, str(next(self._count))))
        step = os.path.join(root, "steps", step_file + ".md")
        with open(step) as f:
            text = f.read()
        if text.startswith("---\n"):
            text = text.replace("---\n", "---\n%s\n" % line, 1)
        else:
            text = "---\n%s\n---\n%s" % (line, text)
        with open(step, "w") as f:
            f.write(text)
        if requires:
            with open(os.path.join(root, "source.toml"), "a") as f:
                f.write('requires-engine = ">=0.6.0"\n')
        return root

    def test_a_review_outcome_the_stage_can_emit_reports_nothing(self):
        rc, _out, err = run_check(
            "--dir", self._build("review-code", "review: done"), "spec-driven")
        self.assertEqual(rc, 0, err)

    def test_a_terminal_outcome_written_without_a_target_counts(self):
        rc, _out, err = run_check(
            "--dir", self._build("await-merge", "sends-back: changes, merged"), "spec-driven")
        self.assertEqual(rc, 0, err)

    def test_an_empty_review_value_is_reported(self):
        rc, _out, err = run_check("--dir", self._build("review-code", "review:"), "spec-driven")
        self.assertEqual(rc, 1)
        self.assertIn("step review-code declares an empty review:", err)

    def test_an_empty_sends_back_value_is_reported(self):
        rc, _out, err = run_check(
            "--dir", self._build("await-merge", "sends-back:"), "spec-driven")
        self.assertEqual(rc, 1)
        self.assertIn("step await-merge declares an empty sends-back:", err)

    def test_a_review_outcome_no_bound_stage_emits_is_reported(self):
        rc, _out, err = run_check(
            "--dir", self._build("review-code", "review: approved"), "spec-driven")
        self.assertEqual(rc, 1)
        self.assertIn("declares review: approved, which is not an outcome", err)

    def test_a_sends_back_outcome_no_bound_stage_emits_is_reported(self):
        rc, _out, err = run_check(
            "--dir", self._build("await-merge", "sends-back: changes, nope"), "spec-driven")
        self.assertEqual(rc, 1)
        self.assertIn("declares sends-back: nope, which is not an outcome", err)

    def test_either_key_without_requires_engine_is_reported(self):
        rc, _out, err = run_check(
            "--dir", self._build("review-code", "review: done", requires=False), "spec-driven")
        self.assertEqual(rc, 1)
        self.assertIn("declares review: but source.toml has no requires-engine", err)
        rc, _out, err = run_check(
            "--dir", self._build("await-merge", "sends-back: changes", requires=False),
            "spec-driven")
        self.assertEqual(rc, 1)
        self.assertIn("declares sends-back: but source.toml has no requires-engine", err)


class TestWorkflowCheckDirScriptStages(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        cli.set_container(_Container())

    def _check(self, **kwargs):
        write_script_bundle(self.tmp, **kwargs)
        return run_check("--dir", self.tmp, "build")

    def test_a_correct_script_stage_passes(self):
        rc, _out, err = self._check()
        self.assertEqual((rc, err), (0, ""))

    def test_a_missing_fixture_fails_naming_it(self):
        rc, _out, err = self._check(stage_fixture=None)
        self.assertNotEqual(rc, 0)
        self.assertIn("fixtures/poll.sh.json", err)

    def test_a_non_executable_script_fails_naming_it(self):
        rc, _out, err = self._check(poll_executable=False)
        self.assertNotEqual(rc, 0)
        self.assertIn("not executable", err)

    def _include_plain_language(self):
        path = os.path.join(self.tmp, "steps", "poll.md")
        with open(path, "a") as f:
            f.write("\n@include plain-language\n")

    def test_a_missing_fixture_is_found_when_a_step_includes_an_engine_fragment(self):
        write_script_bundle(self.tmp, stage_fixture=None)
        self._include_plain_language()
        rc, _out, err = run_check("--dir", self.tmp, "build")
        self.assertNotEqual(rc, 0)
        self.assertIn("fixtures/poll.sh.json", err)

    def test_a_step_with_an_unknown_include_is_reported_naming_the_fragment(self):
        write_script_bundle(self.tmp)
        with open(os.path.join(self.tmp, "steps", "poll.md"), "a") as f:
            f.write("\n@include no-such-fragment\n")
        rc, _out, err = run_check("--dir", self.tmp, "build")
        self.assertNotEqual(rc, 0)
        self.assertIn("no-such-fragment", err)
