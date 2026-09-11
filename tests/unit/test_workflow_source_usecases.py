import os
import tempfile
import unittest

from lightcycle.adapters.fsio import FsAdapter
from lightcycle.adapters.scaffold import ScaffoldAdapter
from lightcycle.application.workflows.add import AddWorkflowSourceUseCase
from lightcycle.application.workflows.init_origin import InitWorkflowOriginUseCase
from lightcycle.domain.workflows.contract import ENGINE_CONTRACT
from lightcycle.application.workflows.list import ListWorkflowSourcesUseCase
from lightcycle.application.workflows.remove import RemoveWorkflowSourceUseCase
from lightcycle.application.workflows.upgrade import (
    UpgradeWorkflowSourceUseCase, UpgradeWorkflowSourcesUseCase,
)
from lightcycle.ports.workflow_source import FetchedBundle, OriginRegistration, WorkflowSourceError
from tests.support.fake_git import FakeGit
from tests.support.fake_store import FakeStore


def _step_text(meta, body=""):
    lines = ["---"] + ["%s: %s" % (k, v) for k, v in meta.items()] + ["---"]
    if body:
        lines.append(body)
    return "\n".join(lines) + "\n"


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


def _add(source, store=None, config=None):
    config = config or FakeConfig()
    return AddWorkflowSourceUseCase(source, store or FakeStore(), config, FsAdapter(config))


class TestAdd(unittest.TestCase):
    def test_add_registers_and_materializes(self):
        source = FakeSource()
        source.add_remote("u", 'name = "acme"\ncontract = 1\n', "sha1")
        resp = _add(source).execute(url="u", ref="main", name=None)
        self.assertEqual(resp.origin, "acme")
        self.assertEqual(resp.sha, "sha1")
        self.assertTrue(source.has_version("acme", "sha1"))
        self.assertEqual(source.read_registry("acme"),
                         OriginRegistration(url="u", ref="main", current="sha1"))

    def test_no_ref_flows_through_to_fetch_and_registry_unmodified(self):
        source = FakeSource()
        source.add_remote("u", 'name = "acme"\ncontract = 1\n', "sha1")
        _add(source).execute(url="u", ref=None, name=None)
        self.assertIsNone(source.last_ref)
        self.assertIsNone(source.read_registry("acme").ref)

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

    def test_add_existing_origin_raises(self):
        source = FakeSource()
        source.add_remote("u", 'name = "acme"\ncontract = 1\n', "sha1")
        _add(source).execute(url="u", ref="main", name=None)
        with self.assertRaises(WorkflowSourceError):
            _add(source).execute(url="u", ref="main", name=None)

    def test_unresolved_step_reference_raises_and_registers_nothing(self):
        source = FakeSource()
        source.add_remote(
            "u", 'name = "acme"\ncontract = 1\n', "sha1",
            workflows={"build": "entry: missing-step\n"})
        with self.assertRaises(WorkflowSourceError):
            _add(source).execute(url="u", ref="main", name=None)
        self.assertEqual(source.list_origins(), [])

    def test_prompt_drift_raises_and_registers_nothing(self):
        source = FakeSource()
        source.add_remote(
            "u", 'name = "acme"\ncontract = 1\n', "sha1",
            steps={"code": _step_text(
                {"model": "x", "step": "code"}, "1. Run `lc frobnicate STEP` and exit.")},
            workflows={"build": "entry: code\n"})
        with self.assertRaises(WorkflowSourceError) as caught:
            _add(source).execute(url="u", ref="main", name=None)
        self.assertIn("`lc frobnicate` is not a command", str(caught.exception))
        self.assertEqual(source.list_origins(), [])

    def test_prompt_drift_names_the_step_and_the_remedy(self):
        source = FakeSource()
        source.add_remote(
            "u", 'name = "acme"\ncontract = 1\n', "sha1",
            steps={"code": _step_text(
                {"model": "x", "step": "code"}, "1. Take `.parent` as ITEM.")},
            workflows={"build": "entry: code\n"})
        with self.assertRaises(WorkflowSourceError) as caught:
            _add(source).execute(url="u", ref="main", name=None)
        message = str(caught.exception)
        self.assertIn("steps/code.md", message)
        self.assertIn("the engine emits no `.parent`", message)
        self.assertIn("fix the step prompts in the source", message)

    def test_destination_only_fileless_terminal_pulls_cleanly(self):
        source = FakeSource()
        source.add_remote(
            "u", 'name = "acme"\ncontract = 1\n', "sha1",
            steps={"code": _step_text({"model": "x", "step": "code"})},
            workflows={"build": "entry: code\n\nedges:\n  code  done  review-conflict\n"})
        resp = _add(source).execute(url="u", ref="main", name=None)
        self.assertEqual(resp.origin, "acme")
        self.assertTrue(source.has_version("acme", "sha1"))


class TestUpgrade(unittest.TestCase):
    def test_upgrade_pulls_new_sha_and_reports_changed(self):
        source = FakeSource()
        source.add_remote("u", 'name = "acme"\ncontract = 1\n', "sha1")
        _add(source).execute(url="u", ref="main", name=None)
        source.add_remote("u", 'name = "acme"\ncontract = 1\n', "sha2")
        cfg = FakeConfig()
        resp = UpgradeWorkflowSourceUseCase(source, FakeStore(), cfg, FsAdapter(cfg)).execute("acme")
        self.assertEqual(resp.sha, "sha2")
        self.assertTrue(resp.changed)
        self.assertEqual(source.read_registry("acme").current, "sha2")

    def test_upgrade_refuses_prompt_drift_and_leaves_the_current_sha(self):
        source = FakeSource()
        source.add_remote("u", 'name = "acme"\ncontract = 1\n', "sha1")
        _add(source).execute(url="u", ref="main", name=None)
        source.add_remote(
            "u", 'name = "acme"\ncontract = 1\n', "sha2",
            steps={"code": _step_text(
                {"model": "x", "step": "code"}, "1. Run `lc frobnicate STEP` and exit.")},
            workflows={"build": "entry: code\n"})
        cfg = FakeConfig()
        with self.assertRaises(WorkflowSourceError):
            UpgradeWorkflowSourceUseCase(source, FakeStore(), cfg, FsAdapter(cfg)).execute("acme")
        self.assertEqual(source.read_registry("acme").current, "sha1")
        self.assertFalse(source.has_version("acme", "sha2"))

    def test_upgrade_unregistered_origin_raises(self):
        cfg = FakeConfig()
        with self.assertRaises(WorkflowSourceError):
            UpgradeWorkflowSourceUseCase(
                FakeSource(), FakeStore(), cfg, FsAdapter(cfg)).execute("nope")

    def test_upgrade_prunes_beyond_retention_but_keeps_pinned(self):
        source = FakeSource()
        store = FakeStore()
        store.create_item("t", "d", workflow="acme/build@sha1")
        cfg = FakeConfig(retention=1)
        fs = FsAdapter(cfg)
        source.add_remote("u", 'name = "acme"\ncontract = 1\n', "sha1")
        AddWorkflowSourceUseCase(source, store, cfg, fs).execute(url="u", ref="main", name=None)
        source.add_remote("u", 'name = "acme"\ncontract = 1\n', "sha2")
        UpgradeWorkflowSourceUseCase(source, store, cfg, fs).execute("acme")
        source.add_remote("u", 'name = "acme"\ncontract = 1\n', "sha3")
        UpgradeWorkflowSourceUseCase(source, store, cfg, fs).execute("acme")
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
        cfg = FakeConfig()
        resp = UpgradeWorkflowSourcesUseCase(source, FakeStore(), cfg, FsAdapter(cfg)).execute()
        self.assertEqual(len(resp.results), 1)
        self.assertEqual(resp.results[0].origin, "healthy")
        self.assertEqual(resp.results[0].sha, "sha2")
        self.assertEqual(len(resp.failures), 1)
        self.assertEqual(resp.failures[0].origin, "broken")
        self.assertEqual(resp.failures[0].error, "ref 'branch-x' not found in u2")


class TestRemove(unittest.TestCase):
    def test_remove_refuses_when_a_live_item_pins_a_version(self):
        source = FakeSource()
        store = FakeStore()
        store.create_item("t", "d", workflow="acme/build@sha1")
        source.add_remote("u", 'name = "acme"\ncontract = 1\n', "sha1")
        cfg = FakeConfig()
        AddWorkflowSourceUseCase(source, store, cfg, FsAdapter(cfg)).execute(
            url="u", ref="main", name=None)
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
        store = FakeStore()
        store.create_item("t", "d", workflow="acme/build@sha1")
        cfg = FakeConfig(retention=5)
        fs = FsAdapter(cfg)
        source.add_remote("u", 'name = "acme"\ncontract = 1\n', "sha1")
        AddWorkflowSourceUseCase(source, store, cfg, fs).execute(url="u", ref="main", name=None)
        source.add_remote("u", 'name = "acme"\ncontract = 1\n', "sha2")
        UpgradeWorkflowSourceUseCase(source, store, cfg, fs).execute("acme")
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
            InitWorkflowOriginUseCase(
                cfg, git, FakeSource(), FakeStore(), ScaffoldAdapter(), FsAdapter(cfg)
            ).execute("acme")
        self.assertEqual(git.calls, [])

    def test_creates_scaffold_registers_with_head_ref_and_sets_personal_origin(self):
        root = tempfile.mkdtemp()
        project_dir = os.path.join(root, "acme")
        cfg = FakeConfig(projects_root=root)
        source = FakeSource()
        source.add_remote(project_dir, 'name = "acme"\ncontract = 1\n', "sha1")
        git = FakeGit()
        resp = InitWorkflowOriginUseCase(
            cfg, git, source, FakeStore(), ScaffoldAdapter(), FsAdapter(cfg)
        ).execute("acme")
        self.assertEqual(resp.project_dir, project_dir)
        self.assertEqual(resp.origin, "acme")
        self.assertEqual(resp.sha, "sha1")
        self.assertTrue(os.path.isfile(os.path.join(project_dir, "source.toml")))
        self.assertTrue(os.path.isfile(os.path.join(project_dir, "CLAUDE.md")))
        self.assertTrue(os.path.isfile(os.path.join(project_dir, ".github", "workflows", "simulate.yml")))
        self.assertTrue(os.path.isfile(os.path.join(project_dir, "README.md")))
        self.assertEqual(source.last_ref, "HEAD")
        self.assertEqual(source.read_registry("acme").current, "sha1")
        self.assertEqual(cfg.personal_origin_set, "acme")
        self.assertIn(("init_repo", project_dir, "main"), git.calls)
        self.assertIn(("commit_all", project_dir, "scaffold workflow-origin repo"), git.calls)

    def test_scaffold_writes_canonical_simulate_yml(self):
        root = tempfile.mkdtemp()
        project_dir = os.path.join(root, "acme")
        cfg = FakeConfig(projects_root=root)
        source = FakeSource()
        source.add_remote(project_dir, 'name = "acme"\ncontract = 1\n', "sha1")
        InitWorkflowOriginUseCase(
            cfg, FakeGit(), source, FakeStore(), ScaffoldAdapter(), FsAdapter(cfg)
        ).execute("acme")
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

    def test_scaffold_writes_canonical_source_toml(self):
        root = tempfile.mkdtemp()
        project_dir = os.path.join(root, "acme")
        cfg = FakeConfig(projects_root=root)
        source = FakeSource()
        source.add_remote(project_dir, 'name = "acme"\ncontract = 1\n', "sha1")
        InitWorkflowOriginUseCase(
            cfg, FakeGit(), source, FakeStore(), ScaffoldAdapter(), FsAdapter(cfg)
        ).execute("acme")
        with open(os.path.join(project_dir, "source.toml")) as f:
            content = f.read()
        self.assertEqual(content, """name = "acme"
contract = %d
description = "Personal workflow origin: acme."
""" % ENGINE_CONTRACT)

    def test_scaffold_writes_canonical_claude_md(self):
        root = tempfile.mkdtemp()
        project_dir = os.path.join(root, "acme")
        cfg = FakeConfig(projects_root=root)
        source = FakeSource()
        source.add_remote(project_dir, 'name = "acme"\ncontract = 1\n', "sha1")
        InitWorkflowOriginUseCase(
            cfg, FakeGit(), source, FakeStore(), ScaffoldAdapter(), FsAdapter(cfg)
        ).execute("acme")
        with open(os.path.join(project_dir, "CLAUDE.md")) as f:
            content = f.read()
        self.assertEqual(content, """# CLAUDE.md - acme

A **workflow origin**: a pullable `lc` source. `source.toml` names it and declares the engine contract it targets; `workflows/*.md` are graphs (`entry`/`requires`/`workspace`/`phase`/`nodes`/`edges`/`hooks`/`signals`); `steps/*.md` are the agent role prompts a graph's stages reference. `lc workflow add`/`upgrade` pulls this repo into an immutable, sha-pinned bundle; each item then pins one `<origin>/<name>@<sha>`.

## The self-contained-bundle rule

A workflow in this repo may reference only step files inside this same repo (`steps/*.md`) - never a file in another origin, and never the `lc` engine's own `lightcycle/prompts/` (those are the engine's own driver/audit prompts, not workflow content). A bundle that reaches outside itself is not portable: `lc workflow add` pins a single sha, so an external reference resolves against whatever that other location happened to contain at pull time, or nothing at all.

## Building a workflow here

Author with the `lightcycle:author-workflow` skill. If this origin has no workflow yet, bootstrap the first one with a generic pipeline (e.g. `spec-driven`) pointed at this repo, the same way `lightcycle-workflows` bootstrapped its own `workflow-authoring` workflow. Model a new graph and its step prompts on bundles already pulled from the `lightcycle` origin (`spec-driven`, `bdd-driven`, `workflow-authoring`) - never on the engine source (`lightcycle/prompts/driver.md` and its neighbors are the engine's own prompts, not a workflow template).

## The gate is the simulator, not a test suite

`lc workflow check <origin>/<name>` (static composition) and the `simulate` CI job (`.github/workflows/simulate.yml`) are what a PR touching `workflows/*.md` or `steps/*.md` must pass. That gate installs the engine at `ENGINE_PIN`, which starts as `main` - set it to a SHA you have watched pass every bundle here, so a PR's result depends only on its own diff. The nightly run always tracks the engine's `main`, so upstream drift surfaces as a scheduled failure rather than as a false `ci-failed` rework on an unrelated PR. `lc workflow describe <origin>/<name> --mermaid` renders the built graph so a reviewer can confirm it matches the design.

## Style

Format every file with `npx prettier --write` **except** `workflows/*.md` - its `entry`/`requires`/`workspace`/`phase`/`nodes`/`edges`/`hooks`/`signals` blocks are a structured graph grammar, not prose, and prettier's markdown formatter reflows them.
""")

    def test_scaffold_writes_canonical_readme_md(self):
        root = tempfile.mkdtemp()
        project_dir = os.path.join(root, "acme")
        cfg = FakeConfig(projects_root=root)
        source = FakeSource()
        source.add_remote(project_dir, 'name = "acme"\ncontract = 1\n', "sha1")
        InitWorkflowOriginUseCase(
            cfg, FakeGit(), source, FakeStore(), ScaffoldAdapter(), FsAdapter(cfg)
        ).execute("acme")
        with open(os.path.join(project_dir, "README.md")) as f:
            content = f.read()
        self.assertEqual(content, """# acme

A personal `lc` workflow origin (see `CLAUDE.md`). No workflow bundles yet - author the first one with the `lightcycle:author-workflow` skill.

| Workflow | Gates | Summary |
| -------- | ----- | ------- |
""")

    def test_scaffold_contains_no_hardcoded_name(self):
        root = tempfile.mkdtemp()
        project_dir = os.path.join(root, "acme")
        cfg = FakeConfig(projects_root=root)
        source = FakeSource()
        source.add_remote(project_dir, 'name = "acme"\ncontract = 1\n', "sha1")
        InitWorkflowOriginUseCase(
            cfg, FakeGit(), source, FakeStore(), ScaffoldAdapter(), FsAdapter(cfg)
        ).execute("acme")
        for fname in ("source.toml", "README.md"):
            with open(os.path.join(project_dir, fname)) as f:
                text = f.read()
            self.assertNotIn("lightcycle-workflows", text)


if __name__ == "__main__":
    unittest.main()
