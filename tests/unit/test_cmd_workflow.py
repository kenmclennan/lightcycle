import io
import unittest
from contextlib import redirect_stdout, redirect_stderr

from lightcycle import cli
from lightcycle.application.workflows.list import ListWorkflowSourcesUseCase
from lightcycle.domain.flow import Flow
from lightcycle.domain.flow.graph import parse_graph
from lightcycle.render import render_workflow_mermaid
from tests.support.fake_fs import FakeFs
from tests.support.fake_store import FakeStore as SupportStore
from tests.unit.test_flow_from_graph import GRAPH_TEXT, STEP_METAS


class TestWorkflowListSummaries(unittest.TestCase):
    def test_list_shows_each_workflows_summary(self):
        source = FakeSource()
        source.registries["acme"] = {"url": "u", "ref": "main", "current": "sha1"}
        source.materialized["acme"] = ["sha1"]
        source.workflow_names = lambda o, s: ["bdd-driven", "spec-driven"]
        fs = FakeFs(workflows={
            "spec-driven": "---\nsummary: spec to merged\n---\nentry: x\n",
            "bdd-driven": "---\nsummary: gherkin first\n---\nentry: y\n",
        })
        resp = ListWorkflowSourcesUseCase(source, SupportStore(), fs).execute()
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
        self._checkouts = {}
        self._n = 0
        self.last_ref = None

    def add_remote(self, url, manifest, sha):
        self.remotes[url] = (manifest, sha)

    def fetch(self, url, ref):
        manifest, sha = self.remotes[url]
        self._n += 1
        checkout = "c-%d" % self._n
        self._checkouts[checkout] = manifest
        self.last_ref = ref
        return checkout, sha

    def read_manifest(self, checkout_dir):
        return self._checkouts[checkout_dir]

    def materialize(self, origin, sha, checkout_dir):
        self.materialized.setdefault(origin, [])
        if sha not in self.materialized[origin]:
            self.materialized[origin].append(sha)
        return "%s/%s" % (origin, sha)

    def has_version(self, origin, sha):
        return sha in self.materialized.get(origin, [])

    def bundle_path(self, origin, sha):
        return "%s/%s" % (origin, sha)

    def workflow_names(self, origin, sha):
        return []

    def write_registry(self, origin, url, ref, current):
        self.registries[origin] = {"url": url, "ref": ref, "current": current}

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

    def cleanup(self, checkout_dir):
        pass


class _Node:
    def __init__(self, workflow):
        self.workflow = workflow


class FakeStore:
    def __init__(self, nodes=None):
        self._nodes = nodes or []

    def all_nodes(self):
        return list(self._nodes)


class FakeConfig:
    def workflow_retention(self):
        return 5


class FakeContainer:
    def __init__(self, source, store):
        self.workflow_source = source
        self.store = store
        self.config = FakeConfig()
        self.fs = FakeFs()


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
        self.assertEqual(self.source.read_registry("acme")["current"], "sha1")

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
        self.source.add_remote("u", 'name = "acme"\ncontract = 1\n', "sha1")
        container = FakeContainer(self.source, self.store)
        container.fs = FakeFs(workflows={"build": "entry: missing-step\n"})
        cli.set_container(container)
        rc, out, err = call(cli.cmd_workflow, "add", "u")
        self.assertEqual(rc, 1)
        self.assertIn("missing-step", err)
        self.assertEqual(self.source.list_origins(), [])

    def test_add_incomplete_phase_block_errors(self):
        self.source.add_remote("u", 'name = "acme"\ncontract = 1\n', "sha1")
        container = FakeContainer(self.source, self.store)
        text = (
            "entry: build\n\n"
            "nodes:\n  build  coder\n  review  reviewer\n\n"
            "edges:\n  build  done  review\n\n"
            "phase:\n  build  code\n"
        )
        container.fs = FakeFs(
            metas={"coder": {"model": "x"}, "reviewer": {"model": "x"}},
            workflows={"build": text},
        )
        cli.set_container(container)
        rc, out, err = call(cli.cmd_workflow, "add", "u")
        self.assertEqual(rc, 1)
        self.assertIn("review", err)
        self.assertEqual(self.source.list_origins(), [])

    def test_add_phase_on_fileless_terminal_names_non_owned(self):
        self.source.add_remote("u", 'name = "acme"\ncontract = 1\n', "sha1")
        container = FakeContainer(self.source, self.store)
        text = (
            "entry: build\n\n"
            "nodes:\n  build  coder\n\n"
            "edges:\n  build  done  review\n  build  conflict  review-conflict\n\n"
            "phase:\n  build  code\n  review-conflict  code\n"
        )
        container.fs = FakeFs(
            metas={"coder": {"model": "x"}},
            workflows={"build": text},
        )
        cli.set_container(container)
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
        self.assertEqual(self.source.read_registry("acme")["current"], "sha2")

    def test_list_shows_origin_and_current(self):
        self.source.add_remote("u", 'name = "acme"\ncontract = 1\n', "sha1")
        call(cli.cmd_workflow, "add", "u")
        rc, out, err = call(cli.cmd_workflow, "list")
        self.assertEqual(rc, 0)
        self.assertIn("acme", out)
        self.assertIn("sha1", out)

    def test_rm_deregisters(self):
        self.source.add_remote("u", 'name = "acme"\ncontract = 1\n', "sha1")
        call(cli.cmd_workflow, "add", "u")
        rc, out, err = call(cli.cmd_workflow, "rm", "acme")
        self.assertEqual(rc, 0)
        self.assertEqual(self.source.list_origins(), [])

    def test_rm_refuses_when_pinned(self):
        self.store = FakeStore([_Node("acme/build@sha1")])
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
        cli.set_container(container)
        rc, out, err = call(cli.cmd_workflow, "describe", "acme/build@sha1")
        self.assertEqual(rc, 0)
        flow = Flow.from_graph(parse_graph(GRAPH_TEXT), STEP_METAS)
        expected = (
            "acme/build@sha1\n"
            "  entry        build\n"
            "  steps        %s\n" % ", ".join(flow.steps())
        )
        self.assertEqual(out, expected)
        self.assertNotIn("flowchart", out)

    def test_describe_mermaid_flag_prints_diagram(self):
        self.source.add_remote("u", 'name = "acme"\ncontract = 1\n', "sha1")
        container = FakeContainer(self.source, self.store)
        container.fs = FakeFs(metas=STEP_METAS, workflows={"build": GRAPH_TEXT})
        cli.set_container(container)
        rc, out, err = call(cli.cmd_workflow, "describe", "acme/build@sha1", "--mermaid")
        self.assertEqual(rc, 0)
        graph = parse_graph(GRAPH_TEXT)
        flow = Flow.from_graph(graph, STEP_METAS)
        self.assertEqual(out.splitlines(), render_workflow_mermaid(graph, flow))
        self.assertEqual(out.splitlines()[0], "flowchart TD")


if __name__ == "__main__":
    unittest.main()
