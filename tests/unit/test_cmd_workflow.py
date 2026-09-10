import dataclasses
import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

from lightcycle import cli
from lightcycle.application.workflows.list import ListWorkflowSourcesUseCase
from lightcycle.domain.flow import Flow
from lightcycle.domain.flow.graph import parse_graph
from lightcycle.ports.workflow_source import FetchedBundle, OriginRegistration, WorkflowSourceError
from lightcycle.render import display_stage, render_workflow_mermaid
from lightcycle.adapters.fsio import FsAdapter
from lightcycle.adapters.scaffold import ScaffoldAdapter
from tests.support.fake_fs import FakeFs
from tests.support.fake_git import FakeGit
from tests.support.fake_store import FakeStore
from tests.unit.test_flow_from_graph import GRAPH_TEXT, STEP_METAS


def _step_text(meta, body=""):
    lines = ["---"] + ["%s: %s" % (k, v) for k, v in meta.items()] + ["---"]
    if body:
        lines.append(body)
    return "\n".join(lines) + "\n"


class TestWorkflowListSummaries(unittest.TestCase):
    def test_list_shows_each_workflows_summary(self):
        source = FakeSource()
        source.registries["acme"] = OriginRegistration(url="u", ref="main", current="sha1")
        source.materialized["acme"] = ["sha1"]
        source.workflow_names = lambda o, s: ["bdd-driven", "spec-driven"]
        fs = FakeFs(workflows={
            "spec-driven": "---\nsummary: spec to merged\n---\nentry: x\n",
            "bdd-driven": "---\nsummary: gherkin first\n---\nentry: y\n",
        })
        resp = ListWorkflowSourcesUseCase(source, FakeStore(), fs).execute()
        wfs = dict(resp.origins[0].workflows)
        self.assertEqual(wfs["spec-driven"], "spec to merged")
        self.assertEqual(wfs["bdd-driven"], "gherkin first")


def call(fn, *args):
    out, err = io.StringIO(), io.StringIO()
    try:
        with redirect_stdout(out), redirect_stderr(err):
            rc = fn(list(args)) or 0
    except SystemExit as e:
        rc = e.code if isinstance(e.code, int) else 1
    return rc, out.getvalue(), err.getvalue()


class FakeSource:
    def __init__(self):
        self.remotes = {}
        self.materialized = {}
        self.registries = {}
        self.last_ref = None
        self.failing = {}

    def add_remote(self, url, manifest, sha, steps=None, workflows=None):
        self.remotes[url] = (manifest, sha, steps or {}, workflows or {})

    def fail_remote(self, url, message):
        self.failing[url] = message

    def fetch(self, url, ref):
        if url in self.failing:
            raise WorkflowSourceError(self.failing[url])
        manifest, sha, steps, workflows = self.remotes[url]
        self.last_ref = ref
        return FetchedBundle(manifest=manifest, sha=sha, steps=steps, workflows=workflows)

    def pin(self, origin, bundle):
        self.materialized.setdefault(origin, [])
        if bundle.sha not in self.materialized[origin]:
            self.materialized[origin].append(bundle.sha)
        return "%s/%s" % (origin, bundle.sha)

    def has_version(self, origin, sha):
        return sha in self.materialized.get(origin, [])

    def pinned_bundle(self, origin, sha):
        return "%s/%s" % (origin, sha)

    def workflow_names(self, origin, sha):
        return []

    def write_registry(self, origin, url, ref, current):
        self.registries[origin] = OriginRegistration(url=url, ref=ref, current=current)

    def read_registry(self, origin):
        return self.registries.get(origin)

    def list_origins(self):
        return sorted(self.registries)

    def list_versions(self, origin):
        return list(reversed(self.materialized.get(origin, [])))

    def remove_version(self, origin, sha):
        self.materialized[origin] = [s for s in self.materialized.get(origin, []) if s != sha]

    def remove_origin(self, origin):
        self.materialized.pop(origin, None)
        self.registries.pop(origin, None)


class FakeConfig:
    def __init__(self, projects_root="/projects"):
        self._projects_root = projects_root
        self.personal_origin_set = None

    def workflow_retention(self):
        return 5

    def projects_root(self):
        return self._projects_root

    def set_personal_origin(self, name):
        self.personal_origin_set = name


class FakeContainer:
    def __init__(self, source, store):
        self.workflow_source = source
        self.store = store
        self.config = FakeConfig()
        self.fs = FsAdapter(self.config)
        self.workflow_bundle = FakeFs()
        self.scaffold = ScaffoldAdapter()
        self.git = FakeGit()


class TestCmdWorkflow(unittest.TestCase):
    def setUp(self):
        self.source = FakeSource()
        self.store = FakeStore()
        cli.set_container(FakeContainer(self.source, self.store))

    def test_add_registers_and_reports(self):
        self.source.add_remote("u", 'name = "acme"\ncontract = 1\n', "sha1")
        rc, out, err = call(cli.cmd_workflow, "add", "u")
        self.assertEqual(rc, 0)
        self.assertIn("acme", out)
        self.assertIn("sha1", out)
        self.assertEqual(self.source.read_registry("acme").current, "sha1")

    def test_add_with_no_ref_flag_reaches_the_use_case_as_none(self):
        self.source.add_remote("u", 'name = "acme"\ncontract = 1\n', "sha1")
        rc, out, err = call(cli.cmd_workflow, "add", "u")
        self.assertEqual(rc, 0)
        self.assertIsNone(self.source.last_ref)

    def test_add_name_override(self):
        self.source.add_remote("u", 'name = "acme"\ncontract = 1\n', "sha1")
        rc, out, err = call(cli.cmd_workflow, "add", "u", "--name", "mine")
        self.assertEqual(rc, 0)
        self.assertIn("mine", out)

    def test_add_incompatible_contract_errors(self):
        self.source.add_remote("u", 'name = "acme"\ncontract = 99\n', "sha1")
        rc, out, err = call(cli.cmd_workflow, "add", "u")
        self.assertEqual(rc, 1)
        self.assertIn("contract", err)
        self.assertEqual(self.source.list_origins(), [])

    def test_add_unresolved_step_reference_errors(self):
        self.source.add_remote(
            "u", 'name = "acme"\ncontract = 1\n', "sha1",
            workflows={"build": "entry: missing-step\n"})
        rc, out, err = call(cli.cmd_workflow, "add", "u")
        self.assertEqual(rc, 1)
        self.assertIn("missing-step", err)
        self.assertEqual(self.source.list_origins(), [])

    def test_add_incomplete_phase_block_errors(self):
        text = (
            "entry: build\n\n"
            "nodes:\n  build  coder\n  review  reviewer\n\n"
            "edges:\n  build  done  review\n\n"
            "phase:\n  build  code\n"
        )
        self.source.add_remote(
            "u", 'name = "acme"\ncontract = 1\n', "sha1",
            steps={
                "coder": _step_text({"model": "x"}),
                "reviewer": _step_text({"model": "x"}),
            },
            workflows={"build": text})
        rc, out, err = call(cli.cmd_workflow, "add", "u")
        self.assertEqual(rc, 1)
        self.assertIn("review", err)
        self.assertEqual(self.source.list_origins(), [])

    def test_add_phase_on_fileless_terminal_names_non_owned(self):
        text = (
            "entry: build\n\n"
            "nodes:\n  build  coder\n\n"
            "edges:\n  build  done  review\n  build  conflict  review-conflict\n\n"
            "phase:\n  build  code\n  review-conflict  code\n"
        )
        self.source.add_remote(
            "u", 'name = "acme"\ncontract = 1\n', "sha1",
            steps={"coder": _step_text({"model": "x"})},
            workflows={"build": text})
        rc, out, err = call(cli.cmd_workflow, "add", "u")
        self.assertEqual(rc, 1)
        self.assertNotIn("unknown stage", err)
        self.assertIn("non-owned stage", err)
        self.assertIn("only owned stages carry a phase", err)
        self.assertIn("review-conflict", err)
        self.assertEqual(self.source.list_origins(), [])

    def test_upgrade_no_origin_upgrades_all_registered(self):
        self.source.add_remote("u", 'name = "acme"\ncontract = 1\n', "sha1")
        call(cli.cmd_workflow, "add", "u")
        self.source.add_remote("u", 'name = "acme"\ncontract = 1\n', "sha2")
        rc, out, err = call(cli.cmd_workflow, "upgrade")
        self.assertEqual(rc, 0)
        self.assertIn("sha2", out)
        self.assertEqual(self.source.read_registry("acme").current, "sha2")

    def test_upgrade_reports_every_origin_even_when_one_fails(self):
        self.source.add_remote("u1", 'name = "first"\ncontract = 1\n', "sha1")
        self.source.add_remote("u2", 'name = "second"\ncontract = 1\n', "sha1")
        self.source.add_remote("u3", 'name = "third"\ncontract = 1\n', "sha1")
        call(cli.cmd_workflow, "add", "u1")
        call(cli.cmd_workflow, "add", "u2")
        call(cli.cmd_workflow, "add", "u3")
        self.source.add_remote("u1", 'name = "first"\ncontract = 1\n', "sha2")
        self.source.add_remote("u3", 'name = "third"\ncontract = 1\n', "sha2")
        self.source.fail_remote("u2", "ref 'branch-x' not found in u2")
        first_before = self.source.read_registry("first")
        second_before = self.source.read_registry("second")
        third_before = self.source.read_registry("third")
        rc, out, err = call(cli.cmd_workflow, "upgrade")
        self.assertEqual(rc, 1)
        self.assertIn("upgraded first @ sha2", out)
        self.assertIn("upgraded third @ sha2", out)
        self.assertIn("second", err)
        self.assertIn("ref 'branch-x' not found in u2", err)
        self.assertEqual(
            self.source.read_registry("first"), dataclasses.replace(first_before, current="sha2"))
        self.assertEqual(self.source.read_registry("second"), second_before)
        self.assertEqual(
            self.source.read_registry("third"), dataclasses.replace(third_before, current="sha2"))

    def test_upgrade_all_origins_failing_reports_each_and_exits_nonzero(self):
        self.source.add_remote("u1", 'name = "first"\ncontract = 1\n', "sha1")
        self.source.add_remote("u2", 'name = "second"\ncontract = 1\n', "sha1")
        call(cli.cmd_workflow, "add", "u1")
        call(cli.cmd_workflow, "add", "u2")
        self.source.fail_remote("u1", "boom-first")
        self.source.fail_remote("u2", "boom-second")
        rc, out, err = call(cli.cmd_workflow, "upgrade")
        self.assertEqual(rc, 1)
        self.assertIn("first", err)
        self.assertIn("boom-first", err)
        self.assertIn("second", err)
        self.assertIn("boom-second", err)

    def test_upgrade_explicit_failing_origin_reports_and_exits_nonzero(self):
        self.source.add_remote("u", 'name = "acme"\ncontract = 1\n', "sha1")
        call(cli.cmd_workflow, "add", "u")
        self.source.fail_remote("u", "ref 'branch-x' not found in u")
        rc, out, err = call(cli.cmd_workflow, "upgrade", "acme")
        self.assertEqual(rc, 1)
        self.assertIn("acme", err)
        self.assertIn("ref 'branch-x' not found in u", err)

    def test_upgrade_no_origins_registered_reports_and_exits_zero(self):
        rc, out, err = call(cli.cmd_workflow, "upgrade")
        self.assertEqual(rc, 0)
        self.assertIn("no workflow sources registered", out)

    def test_list_shows_origin_and_current(self):
        self.source.add_remote("u", 'name = "acme"\ncontract = 1\n', "sha1")
        call(cli.cmd_workflow, "add", "u")
        rc, out, err = call(cli.cmd_workflow, "list")
        self.assertEqual(rc, 0)
        self.assertIn("acme", out)
        self.assertIn("sha1", out)

    def test_list_shows_ref_when_pinned_and_omits_it_when_not(self):
        self.source.add_remote("u1", 'name = "pinned"\ncontract = 1\n', "sha1")
        call(cli.cmd_workflow, "add", "u1", "--ref", "branch-x", "--name", "pinned")
        self.source.add_remote("u2", 'name = "unpinned"\ncontract = 1\n', "sha1")
        call(cli.cmd_workflow, "add", "u2", "--name", "unpinned")
        rc, out, err = call(cli.cmd_workflow, "list")
        self.assertEqual(rc, 0)
        lines = out.splitlines()
        pinned_line = next(l for l in lines if l.startswith("pinned "))
        unpinned_line = next(l for l in lines if l.startswith("unpinned "))
        self.assertIn("branch-x", pinned_line)
        self.assertNotEqual(pinned_line, unpinned_line)
        self.assertNotIn("branch-x", unpinned_line)

    def test_rm_deregisters(self):
        self.source.add_remote("u", 'name = "acme"\ncontract = 1\n', "sha1")
        call(cli.cmd_workflow, "add", "u")
        rc, out, err = call(cli.cmd_workflow, "rm", "acme")
        self.assertEqual(rc, 0)
        self.assertEqual(self.source.list_origins(), [])

    def test_rm_refuses_when_pinned(self):
        self.store = FakeStore()
        self.store.create_item("t", "d", workflow="acme/build@sha1")
        cli.set_container(FakeContainer(self.source, self.store))
        self.source.add_remote("u", 'name = "acme"\ncontract = 1\n', "sha1")
        call(cli.cmd_workflow, "add", "u")
        rc, out, err = call(cli.cmd_workflow, "rm", "acme")
        self.assertEqual(rc, 1)
        self.assertIn("pin", err)
        self.assertEqual(self.source.list_origins(), ["acme"])

    def test_unknown_subcommand_errors(self):
        rc, out, err = call(cli.cmd_workflow, "frobnicate")
        self.assertEqual(rc, 2)

    def test_describe_prints_summary_entry_and_steps(self):
        self.source.add_remote("u", 'name = "acme"\ncontract = 1\n', "sha1")
        container = FakeContainer(self.source, self.store)
        container.fs = FakeFs(metas=STEP_METAS, workflows={"build": GRAPH_TEXT})
        container.workflow_bundle = container.fs
        cli.set_container(container)
        rc, out, err = call(cli.cmd_workflow, "describe", "acme/build@sha1")
        self.assertEqual(rc, 0)
        flow = Flow.from_graph(parse_graph(GRAPH_TEXT), STEP_METAS)
        expected = (
            "acme/build@sha1\n"
            "  entry        build\n"
            "  steps        %s\n" % ", ".join(
                display_stage(flow.step_def(s).display, s) for s in flow.steps()
            )
        )
        self.assertEqual(out, expected)
        self.assertNotIn("flowchart", out)

    def test_describe_resolves_each_steps_display_phrase(self):
        self.source.add_remote("u", 'name = "acme"\ncontract = 1\n', "sha1")
        container = FakeContainer(self.source, self.store)
        display_graph_text = GRAPH_TEXT + "\ndisplay:\n  build  Coding\n  review  Review the PR\n"
        container.fs = FakeFs(metas=STEP_METAS, workflows={"build": display_graph_text})
        container.workflow_bundle = container.fs
        cli.set_container(container)
        rc, out, err = call(cli.cmd_workflow, "describe", "acme/build@sha1")
        self.assertEqual(rc, 0)
        flow = Flow.from_graph(parse_graph(display_graph_text), STEP_METAS)
        self.assertIn("Coding · build", out)
        self.assertIn("Review the PR · review", out)
        for step in flow.steps():
            if flow.step_def(step).display is None:
                self.assertIn(step, out)

    def test_describe_mermaid_flag_prints_diagram(self):
        self.source.add_remote("u", 'name = "acme"\ncontract = 1\n', "sha1")
        container = FakeContainer(self.source, self.store)
        container.fs = FakeFs(metas=STEP_METAS, workflows={"build": GRAPH_TEXT})
        container.workflow_bundle = container.fs
        cli.set_container(container)
        rc, out, err = call(cli.cmd_workflow, "describe", "acme/build@sha1", "--mermaid")
        self.assertEqual(rc, 0)
        graph = parse_graph(GRAPH_TEXT)
        flow = Flow.from_graph(graph, STEP_METAS)
        self.assertEqual(out.splitlines(), render_workflow_mermaid(graph, flow))
        self.assertEqual(out.splitlines()[0], "flowchart TD")


class TestCmdWorkflowInit(unittest.TestCase):
    def setUp(self):
        self.source = FakeSource()
        self.store = FakeStore()
        self.root = tempfile.mkdtemp()
        self.container = FakeContainer(self.source, self.store)
        self.container.config = FakeConfig(projects_root=self.root)
        cli.set_container(self.container)

    def test_init_creates_scaffold_registers_and_sets_personal_origin(self):
        project_dir = os.path.join(self.root, "acme")
        self.source.add_remote(project_dir, 'name = "acme"\ncontract = 1\n', "sha1")
        rc, out, err = call(cli.cmd_workflow, "init", "acme")
        self.assertEqual(rc, 0)
        self.assertIn("acme", out)
        self.assertIn("sha1", out)
        self.assertTrue(os.path.isfile(os.path.join(project_dir, "source.toml")))
        self.assertEqual(self.source.read_registry("acme").current, "sha1")
        self.assertEqual(self.source.last_ref, "HEAD")
        self.assertEqual(self.container.config.personal_origin_set, "acme")
        self.assertIn(("init_repo", project_dir, "main"), self.container.git.calls)

    def test_init_refuses_when_project_dir_exists(self):
        project_dir = os.path.join(self.root, "acme")
        os.makedirs(project_dir)
        rc, out, err = call(cli.cmd_workflow, "init", "acme")
        self.assertEqual(rc, 1)
        self.assertIn(project_dir, err)
        self.assertEqual(self.source.list_origins(), [])


if __name__ == "__main__":
    unittest.main()
