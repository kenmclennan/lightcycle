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
from lightcycle.domain.work import worker_permitted, worker_refusal_message
from lightcycle.domain.workflows.contract import ENGINE_CONTRACT
from tests.support.fake_store import FakeStore

LIBRARY = Path(__file__).resolve().parents[1] / "support" / "library"
ENGINE_PROMPTS = Path(cli.__file__).resolve().parent / "prompts"


class _Config:
    def prompts_root(self):
        return str(ENGINE_PROMPTS)

    def workflow_retention(self):
        return 5

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


class TestWorkflowCheckDir(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.container = _Container()
        cli.set_container(self.container)

    def test_valid_bundle_passes(self):
        rc, _out, err = run_check("--dir", _bundle(self.tmp), "spec-driven")
        self.assertEqual(rc, 0, err)

    def test_missing_fragment_fails_with_the_not_found_message(self):
        _bundle(self.tmp)
        _break(self.tmp)
        rc, _out, err = run_check("--dir", self.tmp, "spec-driven")
        self.assertEqual(rc, 1)
        self.assertIn("fragment 'nonexistent-frag' included by steps/cleanup.md not found", err)

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
            ["init", "n"], ["list"], ["describe", "o/n"], ["simulate", "o/n"], [],
        ):
            self.assertFalse(worker_permitted("workflow", cli._workflow_flags(args)), args)

    def test_unparseable_workflow_args_are_refused(self):
        with redirect_stderr(io.StringIO()):
            flags = cli._workflow_flags(["bogus"])
        self.assertFalse(worker_permitted("workflow", flags))

    def test_refusal_message_names_the_permitted_form(self):
        self.assertIn("workflow check --dir", worker_refusal_message("rm"))


if __name__ == "__main__":
    unittest.main()
