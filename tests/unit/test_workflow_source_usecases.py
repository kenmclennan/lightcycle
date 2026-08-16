import os
import tempfile
import unittest

from lightcycle.application.workflows.add import AddWorkflowSourceUseCase
from lightcycle.application.workflows.errors import WorkflowSourceError
from lightcycle.application.workflows.init_origin import InitWorkflowOriginUseCase
from lightcycle.application.workflows.list import ListWorkflowSourcesUseCase
from lightcycle.application.workflows.remove import RemoveWorkflowSourceUseCase
from lightcycle.application.workflows.upgrade import (
    UpgradeWorkflowSourceUseCase, UpgradeWorkflowSourcesUseCase,
)
from tests.support.fake_fs import FakeFs


class FakeSource:
    def __init__(self):
        self.remotes = {}
        self.materialized = {}
        self.registries = {}
        self._checkouts = {}
        self.cleaned = []
        self._n = 0
        self.last_ref = None
        self.failing = {}

    def add_remote(self, url, manifest, sha):
        self.remotes[url] = (manifest, sha)

    def fail_remote(self, url, message):
        self.failing[url] = message

    def fetch(self, url, ref):
        if url in self.failing:
            raise WorkflowSourceError(self.failing[url])
        manifest, sha = self.remotes[url]
        self._n += 1
        checkout = "checkout-%d" % self._n
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
        self.cleaned.append(checkout_dir)


class _Node:
    def __init__(self, workflow):
        self.workflow = workflow


class FakeStore:
    def __init__(self, nodes=None):
        self._nodes = nodes or []

    def all_nodes(self):
        return list(self._nodes)


class FakeConfig:
    def __init__(self, retention=3, projects_root="/projects"):
        self._retention = retention
        self._projects_root = projects_root
        self.personal_origin_set = None

    def workflow_retention(self):
        return self._retention

    def projects_root(self):
        return self._projects_root

    def set_personal_origin(self, name):
        self.personal_origin_set = name


class FakeGit:
    def __init__(self):
        self.calls = []

    def git(self, root, *args):
        self.calls.append(("git", root, args))

    def commit_all(self, root, message):
        self.calls.append(("commit_all", root, message))


def _add(source, store=None, config=None, fs=None):
    return AddWorkflowSourceUseCase(source, store or FakeStore(), config or FakeConfig(), fs or FakeFs())


class TestAdd(unittest.TestCase):
    def test_add_registers_and_materializes(self):
        source = FakeSource()
        source.add_remote("u", 'name = "acme"\ncontract = 1\n', "sha1")
        resp = _add(source).execute(url="u", ref="main", name=None)
        self.assertEqual(resp.origin, "acme")
        self.assertEqual(resp.sha, "sha1")
        self.assertTrue(source.has_version("acme", "sha1"))
        self.assertEqual(source.read_registry("acme"),
                         {"url": "u", "ref": "main", "current": "sha1"})
        self.assertEqual(source.cleaned, ["checkout-1"])

    def test_no_ref_flows_through_to_fetch_and_registry_unmodified(self):
        source = FakeSource()
        source.add_remote("u", 'name = "acme"\ncontract = 1\n', "sha1")
        _add(source).execute(url="u", ref=None, name=None)
        self.assertIsNone(source.last_ref)
        self.assertIsNone(source.read_registry("acme")["ref"])

    def test_name_flag_overrides_manifest_name(self):
        source = FakeSource()
        source.add_remote("u", 'name = "acme"\ncontract = 1\n', "sha1")
        resp = _add(source).execute(url="u", ref="main", name="mine")
        self.assertEqual(resp.origin, "mine")

    def test_missing_origin_name_raises(self):
        source = FakeSource()
        source.add_remote("u", "contract = 1\n", "sha1")
        with self.assertRaises(WorkflowSourceError):
            _add(source).execute(url="u", ref="main", name=None)

    def test_incompatible_contract_raises_and_registers_nothing(self):
        source = FakeSource()
        source.add_remote("u", 'name = "acme"\ncontract = 99\n', "sha1")
        with self.assertRaises(WorkflowSourceError):
            _add(source).execute(url="u", ref="main", name=None)
        self.assertEqual(source.list_origins(), [])
        self.assertEqual(source.cleaned, ["checkout-1"])

    def test_add_existing_origin_raises(self):
        source = FakeSource()
        source.add_remote("u", 'name = "acme"\ncontract = 1\n', "sha1")
        _add(source).execute(url="u", ref="main", name=None)
        with self.assertRaises(WorkflowSourceError):
            _add(source).execute(url="u", ref="main", name=None)

    def test_unresolved_step_reference_raises_and_registers_nothing(self):
        source = FakeSource()
        source.add_remote("u", 'name = "acme"\ncontract = 1\n', "sha1")
        fs = FakeFs(workflows={"build": "entry: missing-step\n"})
        with self.assertRaises(WorkflowSourceError):
            _add(source, fs=fs).execute(url="u", ref="main", name=None)
        self.assertEqual(source.list_origins(), [])
        self.assertEqual(source.cleaned, ["checkout-1"])

    def test_destination_only_fileless_terminal_pulls_cleanly(self):
        source = FakeSource()
        source.add_remote("u", 'name = "acme"\ncontract = 1\n', "sha1")
        fs = FakeFs(
            metas={"code": {"model": "x", "step": "code"}},
            workflows={"build": "entry: code\n\nedges:\n  code  done  review-conflict\n"},
        )
        resp = _add(source, fs=fs).execute(url="u", ref="main", name=None)
        self.assertEqual(resp.origin, "acme")
        self.assertTrue(source.has_version("acme", "sha1"))


class TestUpgrade(unittest.TestCase):
    def test_upgrade_pulls_new_sha_and_reports_changed(self):
        source = FakeSource()
        source.add_remote("u", 'name = "acme"\ncontract = 1\n', "sha1")
        _add(source).execute(url="u", ref="main", name=None)
        source.add_remote("u", 'name = "acme"\ncontract = 1\n', "sha2")
        resp = UpgradeWorkflowSourceUseCase(source, FakeStore(), FakeConfig(), FakeFs()).execute("acme")
        self.assertEqual(resp.sha, "sha2")
        self.assertTrue(resp.changed)
        self.assertEqual(source.read_registry("acme")["current"], "sha2")

    def test_upgrade_unregistered_origin_raises(self):
        with self.assertRaises(WorkflowSourceError):
            UpgradeWorkflowSourceUseCase(FakeSource(), FakeStore(), FakeConfig(), FakeFs()).execute("nope")

    def test_upgrade_prunes_beyond_retention_but_keeps_pinned(self):
        source = FakeSource()
        store = FakeStore([_Node("acme/build@sha1")])
        cfg = FakeConfig(retention=1)
        source.add_remote("u", 'name = "acme"\ncontract = 1\n', "sha1")
        AddWorkflowSourceUseCase(source, store, cfg, FakeFs()).execute(url="u", ref="main", name=None)
        source.add_remote("u", 'name = "acme"\ncontract = 1\n', "sha2")
        UpgradeWorkflowSourceUseCase(source, store, cfg, FakeFs()).execute("acme")
        source.add_remote("u", 'name = "acme"\ncontract = 1\n', "sha3")
        UpgradeWorkflowSourceUseCase(source, store, cfg, FakeFs()).execute("acme")
        self.assertEqual(set(source.materialized["acme"]), {"sha1", "sha3"})


class TestUpgradeAll(unittest.TestCase):
    def test_execute_reports_healthy_results_and_failures_separately(self):
        source = FakeSource()
        source.add_remote("u1", 'name = "healthy"\ncontract = 1\n', "sha1")
        _add(source).execute(url="u1", ref="main", name=None)
        source.add_remote("u2", 'name = "broken"\ncontract = 1\n', "sha1")
        _add(source).execute(url="u2", ref="main", name=None)
        source.add_remote("u1", 'name = "healthy"\ncontract = 1\n', "sha2")
        source.fail_remote("u2", "ref 'branch-x' not found in u2")
        resp = UpgradeWorkflowSourcesUseCase(source, FakeStore(), FakeConfig(), FakeFs()).execute()
        self.assertEqual(len(resp.results), 1)
        self.assertEqual(resp.results[0].origin, "healthy")
        self.assertEqual(resp.results[0].sha, "sha2")
        self.assertEqual(len(resp.failures), 1)
        self.assertEqual(resp.failures[0].origin, "broken")
        self.assertEqual(resp.failures[0].error, "ref 'branch-x' not found in u2")


class TestRemove(unittest.TestCase):
    def test_remove_refuses_when_a_live_item_pins_a_version(self):
        source = FakeSource()
        store = FakeStore([_Node("acme/build@sha1")])
        source.add_remote("u", 'name = "acme"\ncontract = 1\n', "sha1")
        AddWorkflowSourceUseCase(source, store, FakeConfig(), FakeFs()).execute(url="u", ref="main", name=None)
        with self.assertRaises(WorkflowSourceError):
            RemoveWorkflowSourceUseCase(source, store).execute("acme")
        self.assertEqual(source.list_origins(), ["acme"])

    def test_remove_deregisters_when_unpinned(self):
        source = FakeSource()
        source.add_remote("u", 'name = "acme"\ncontract = 1\n', "sha1")
        _add(source).execute(url="u", ref="main", name=None)
        RemoveWorkflowSourceUseCase(source, FakeStore()).execute("acme")
        self.assertEqual(source.list_origins(), [])

    def test_remove_unregistered_raises(self):
        with self.assertRaises(WorkflowSourceError):
            RemoveWorkflowSourceUseCase(FakeSource(), FakeStore()).execute("nope")


class TestList(unittest.TestCase):
    def test_list_reports_origins_versions_and_pins(self):
        source = FakeSource()
        store = FakeStore([_Node("acme/build@sha1")])
        cfg = FakeConfig(retention=5)
        source.add_remote("u", 'name = "acme"\ncontract = 1\n', "sha1")
        AddWorkflowSourceUseCase(source, store, cfg, FakeFs()).execute(url="u", ref="main", name=None)
        source.add_remote("u", 'name = "acme"\ncontract = 1\n', "sha2")
        UpgradeWorkflowSourceUseCase(source, store, cfg, FakeFs()).execute("acme")
        resp = ListWorkflowSourcesUseCase(source, store).execute()
        self.assertEqual(len(resp.origins), 1)
        view = resp.origins[0]
        self.assertEqual(view.name, "acme")
        self.assertEqual(view.current, "sha2")
        self.assertEqual(view.url, "u")
        self.assertEqual(set(view.pinned), {"sha1"})
        self.assertEqual(set(view.versions), {"sha1", "sha2"})


class TestInit(unittest.TestCase):
    def test_refuses_when_project_dir_already_exists(self):
        root = tempfile.mkdtemp()
        os.makedirs(os.path.join(root, "acme"))
        cfg = FakeConfig(projects_root=root)
        git = FakeGit()
        with self.assertRaises(WorkflowSourceError):
            InitWorkflowOriginUseCase(cfg, git, FakeSource(), FakeStore(), FakeFs()).execute("acme")
        self.assertEqual(git.calls, [])

    def test_creates_scaffold_registers_with_head_ref_and_sets_personal_origin(self):
        root = tempfile.mkdtemp()
        project_dir = os.path.join(root, "acme")
        cfg = FakeConfig(projects_root=root)
        source = FakeSource()
        source.add_remote(project_dir, 'name = "acme"\ncontract = 1\n', "sha1")
        git = FakeGit()
        resp = InitWorkflowOriginUseCase(cfg, git, source, FakeStore(), FakeFs()).execute("acme")
        self.assertEqual(resp.project_dir, project_dir)
        self.assertEqual(resp.origin, "acme")
        self.assertEqual(resp.sha, "sha1")
        self.assertTrue(os.path.isfile(os.path.join(project_dir, "source.toml")))
        self.assertTrue(os.path.isfile(os.path.join(project_dir, "CLAUDE.md")))
        self.assertTrue(os.path.isfile(os.path.join(project_dir, ".github", "workflows", "simulate.yml")))
        self.assertTrue(os.path.isfile(os.path.join(project_dir, "README.md")))
        self.assertEqual(source.last_ref, "HEAD")
        self.assertEqual(source.read_registry("acme")["current"], "sha1")
        self.assertEqual(cfg.personal_origin_set, "acme")
        self.assertIn(("git", project_dir, ("init", "-q", "-b", "main")), git.calls)
        self.assertIn(("commit_all", project_dir, "scaffold workflow-origin repo"), git.calls)

    def test_scaffold_writes_canonical_simulate_yml(self):
        root = tempfile.mkdtemp()
        project_dir = os.path.join(root, "acme")
        cfg = FakeConfig(projects_root=root)
        source = FakeSource()
        source.add_remote(project_dir, 'name = "acme"\ncontract = 1\n', "sha1")
        InitWorkflowOriginUseCase(cfg, FakeGit(), source, FakeStore(), FakeFs()).execute("acme")
        with open(os.path.join(project_dir, ".github", "workflows", "simulate.yml")) as f:
            content = f.read()
        self.assertEqual(content, """name: simulate

on:
  pull_request:
  push:
    branches: [main]
  schedule:
    - cron: "0 6 * * *"

env:
  ENGINE_PIN: main

jobs:
  simulate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.x"

      - name: Install the lc engine
        run: |
          set -euo pipefail
          if [ "${{ github.event_name }}" = "schedule" ]; then
            ref=main
            echo "scheduled run: tracking the engine's main to surface upstream drift"
          else
            ref="$ENGINE_PIN"
            echo "gate run: engine $ref, so this result depends only on this diff"
          fi
          echo "ENGINE_REF=$ref" >> "$GITHUB_ENV"
          pip install "git+https://github.com/kenmclennan/lightcycle@$ref"
          lc --version

      - name: Dry-run every workflow in this bundle through the real engine
        run: |
          set -euo pipefail
          export LC_HOME="$(mktemp -d)"
          lc init >/dev/null 2>&1 || true
          lc workflow add "$GITHUB_WORKSPACE" --name ci-bundle --ref HEAD
          fail=0
          for f in workflows/*.md; do
            name="$(basename "$f" .md)"
            echo "== lc workflow check ci-bundle/$name =="
            lc workflow check "ci-bundle/$name" || fail=1
            echo "== lc workflow simulate ci-bundle/$name =="
            lc workflow simulate "ci-bundle/$name" || fail=1
            echo "== lc workflow describe ci-bundle/$name --mermaid =="
            lc workflow describe "ci-bundle/$name" --mermaid || fail=1
          done
          exit "$fail"
""")

    def test_scaffold_contains_no_hardcoded_name(self):
        root = tempfile.mkdtemp()
        project_dir = os.path.join(root, "acme")
        cfg = FakeConfig(projects_root=root)
        source = FakeSource()
        source.add_remote(project_dir, 'name = "acme"\ncontract = 1\n', "sha1")
        InitWorkflowOriginUseCase(cfg, FakeGit(), source, FakeStore(), FakeFs()).execute("acme")
        for fname in ("source.toml", "README.md"):
            with open(os.path.join(project_dir, fname)) as f:
                text = f.read()
            self.assertNotIn("lightcycle-workflows", text)


if __name__ == "__main__":
    unittest.main()
