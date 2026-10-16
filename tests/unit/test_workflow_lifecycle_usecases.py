import unittest

from lightcycle.adapters.fsio import FsAdapter
from lightcycle.application.workflows.add import AddWorkflowSourceUseCase
from lightcycle.application.workflows.purge import PurgeWorkflowDataUseCase
from lightcycle.application.workflows.remove import RemoveWorkflowSourceUseCase
from lightcycle.application.workflows.upgrade import (
    UpgradeWorkflowSourceUseCase, UpgradeWorkflowSourcesUseCase,
)
from lightcycle.frontmatter import split_frontmatter
from lightcycle.ports.lifecycle_runner import HookResult
from lightcycle.ports.workflow_source import FetchedBundle, WorkflowSourceError
from tests.support.fake_lifecycle_runner import FakeLifecycleRunner
from tests.support.fake_store import FakeStore
from tests.support.lifecycle_fakes import LifecycleFakeConfig, lifecycle_for
from tests.unit.test_workflow_source_usecases import FakeConfig, FakeSource

MANIFEST = 'name = "acme"\ncontract = 1\nrequires-engine = ">=0.1.0"\n'


STEPS = {"code": "---\nmodel: x\nstep: code\n---\nDo it.\n"}


def workflow_text(install=True, upgrade=True, maintain=False, required=True):
    lines = ["---", "lifecycle:"]
    if install:
        lines.append("  install: scripts/install.sh")
    if upgrade:
        lines.append("  upgrade: scripts/upgrade.sh")
    if maintain:
        lines += ["  maintain: scripts/maintain.sh", "  cron: 0 3 * * *"]
    lines += ["config:", "  api-token: %s" % ("required" if required else "optional"),
              "config-example:", "  api-token: example", "---", "entry: code", ""]
    return "\n".join(lines)


def scripts(*names):
    return {n: (b"#!/bin/sh\n", True) for n in names}


ALL_SCRIPTS = scripts("install.sh", "upgrade.sh", "maintain.sh")


class LifecycleSource(FakeSource):
    def __init__(self):
        super().__init__()
        self.bundles = {}
        self.pin_calls = 0

    def add_remote(self, url, manifest, sha, steps=None, workflows=None, scripts=None):
        super().add_remote(url, manifest, sha, steps, workflows)
        self.remote_scripts = getattr(self, "remote_scripts", {})
        self.remote_scripts[url] = scripts or {}

    def fetch(self, url, ref):
        base = super().fetch(url, ref)
        return FetchedBundle(
            manifest=base.manifest, sha=base.sha, steps=base.steps, workflows=base.workflows,
            scripts=self.remote_scripts.get(url, {}))

    def pin(self, origin, bundle):
        self.pin_calls += 1
        self.bundles[(origin, bundle.sha)] = bundle
        return super().pin(origin, bundle)

    def pinned_bundle(self, origin, sha):
        return "%s/%s" % (origin, sha)

    def workflow_names(self, origin, sha):
        bundle = self.bundles.get((origin, sha))
        return sorted(bundle.workflows) if bundle else []


class PinnedBundles:
    def __init__(self, source):
        self._source = source

    def workflow_meta(self, name, root):
        origin, _, sha = root.partition("/")
        bundle = self._source.bundles.get((origin, sha))
        if bundle is None or name not in bundle.workflows:
            return {}
        meta, _ = split_frontmatter(bundle.workflows[name])
        return meta


class Harness:
    def __init__(self, blocks=None):
        self.source = LifecycleSource()
        self.runner = FakeLifecycleRunner()
        self.config = FakeConfig()
        self.store = FakeStore()
        self.lifecycle = lifecycle_for(
            self.source, bundle=PinnedBundles(self.source),
            config=LifecycleFakeConfig(blocks=blocks or {
                "workflow-acme-build": {"api-token": "tok"},
                "workflow-acme-ship": {"api-token": "tok"},
            }),
            runner=self.runner)

    def remote(self, sha, workflows, scripts=ALL_SCRIPTS, url="u"):
        self.source.add_remote(
            url, MANIFEST, sha, steps=STEPS, workflows=workflows, scripts=scripts)

    def add(self):
        return AddWorkflowSourceUseCase(
            self.source, self.store, self.config, FsAdapter(self.config), self.lifecycle
        ).execute(url="u", ref="main", name=None)

    def upgrade(self, origin="acme"):
        return UpgradeWorkflowSourceUseCase(
            self.source, self.store, self.config, FsAdapter(self.config), self.lifecycle
        ).execute(origin)

    def hooks(self):
        return [
            (c["env"]["LC_WORKFLOW_HOOK"], c["env"]["LC_WORKFLOW_NAME"]) for c in self.runner.calls]


class TestAdd(unittest.TestCase):
    def test_install_runs_once_per_declaring_workflow_in_name_order(self):
        h = Harness()
        h.remote("sha1", {
            "ship": workflow_text(upgrade=False), "build": workflow_text(upgrade=False),
            "plain": "entry: code\n"})
        h.add()
        self.assertEqual(h.hooks(), [("install", "build"), ("install", "ship")])
        self.assertEqual(h.source.read_registry("acme").current, "sha1")

    def test_install_sees_data_dir_config_names_and_sha(self):
        h = Harness()
        h.remote("sha1", {"build": workflow_text(upgrade=False)})
        h.add()
        call = h.runner.calls[0]
        env = call["env"]
        self.assertEqual(env["LC_WORKFLOW_HOOK"], "install")
        self.assertEqual(env["LC_WORKFLOW_ORIGIN"], "acme")
        self.assertEqual(env["LC_WORKFLOW_NAME"], "build")
        self.assertEqual(env["LC_WORKFLOW_SHA"], "sha1")
        self.assertEqual(env["LC_WORKFLOW_CONFIG_API_TOKEN"], "tok")
        self.assertEqual(env["LC_WORKFLOW_DATA_DIR"], "/data/workflow-data/acme/build")
        self.assertEqual(call["cwd"], env["LC_WORKFLOW_DATA_DIR"])
        self.assertEqual(call["script"], "acme/sha1/scripts/install.sh")
        self.assertIn(call["cwd"], h.runner.dirs)
        self.assertEqual(call["timeout"], 300)

    def test_a_failing_install_leaves_nothing_and_names_the_hook(self):
        h = Harness()
        h.remote("sha1", {"build": workflow_text(upgrade=False)})
        h.runner.program("install", HookResult(exit_code=3, output="boom"))
        with self.assertRaises(WorkflowSourceError) as caught:
            h.add()
        message = str(caught.exception)
        for part in ("acme/build", "install", "exited 3", "boom"):
            self.assertIn(part, message)
        self.assertIsNone(h.source.read_registry("acme"))
        self.assertEqual(h.source.list_origins(), [])
        self.assertEqual(h.runner.dirs, set())

    def test_a_later_failure_removes_only_what_this_call_created(self):
        h = Harness()
        h.remote("sha1", {
            "build": workflow_text(upgrade=False), "ship": workflow_text(upgrade=False)})
        h.runner.dirs.add("/data/workflow-data/acme/ship")
        h.runner.program("install", HookResult(exit_code=1, output="no"), workflow="acme/ship")
        with self.assertRaises(WorkflowSourceError):
            h.add()
        self.assertEqual(h.hooks(), [("install", "build"), ("install", "ship")])
        self.assertEqual(h.runner.dirs, {"/data/workflow-data/acme/ship"})
        self.assertIsNone(h.source.read_registry("acme"))

    def test_a_timeout_is_a_failure_that_says_so(self):
        h = Harness()
        h.remote("sha1", {"build": workflow_text(upgrade=False)})
        h.runner.program("install", HookResult(exit_code=None, output="", timed_out=True))
        with self.assertRaises(WorkflowSourceError) as caught:
            h.add()
        self.assertIn("timed out after 300s", str(caught.exception))

    def test_a_malformed_block_refuses_before_anything_is_written(self):
        h = Harness()
        h.remote("sha1", {"build": workflow_text(upgrade=False)}, scripts={})
        with self.assertRaises(WorkflowSourceError) as caught:
            h.add()
        self.assertIn("install.sh does not exist", str(caught.exception))
        self.assertEqual(h.source.pin_calls, 0)
        self.assertEqual(h.runner.calls, [])

    def test_a_non_executable_script_refuses(self):
        h = Harness()
        h.remote("sha1", {"build": workflow_text(upgrade=False)},
                 scripts={"install.sh": (b"x", False)})
        with self.assertRaises(WorkflowSourceError) as caught:
            h.add()
        self.assertIn("not executable", str(caught.exception))

    def test_a_bundle_without_lifecycle_runs_no_hook(self):
        h = Harness()
        h.remote("sha1", {"build": "entry: code\n"}, scripts={})
        h.add()
        self.assertEqual(h.runner.calls, [])


class TestUpgrade(unittest.TestCase):
    def _added(self, first):
        h = Harness()
        h.remote("sha1", first)
        h.add()
        h.runner.calls.clear()
        return h

    def test_upgrade_runs_with_both_shas_and_keeps_the_data_dir(self):
        h = self._added({"build": workflow_text()})
        h.runner.ensure_data_dir("/data/workflow-data/acme/build")
        h.remote("sha2", {"build": workflow_text()})
        h.upgrade()
        self.assertEqual(h.hooks(), [("upgrade", "build")])
        env = h.runner.calls[0]["env"]
        self.assertEqual(env["LC_WORKFLOW_FROM_SHA"], "sha1")
        self.assertEqual(env["LC_WORKFLOW_TO_SHA"], "sha2")
        self.assertEqual(env["LC_WORKFLOW_SHA"], "sha2")
        self.assertIn("/data/workflow-data/acme/build", h.runner.dirs)
        self.assertEqual(h.source.read_registry("acme").current, "sha2")

    def test_a_workflow_new_to_the_origin_gets_install_not_upgrade(self):
        h = self._added({"build": workflow_text()})
        h.remote("sha2", {"build": workflow_text(), "ship": workflow_text()})
        h.upgrade()
        self.assertEqual(h.hooks(), [("upgrade", "build"), ("install", "ship")])

    def test_a_workflow_that_gained_install_gets_install(self):
        h = self._added({"build": workflow_text(install=False)})
        h.remote("sha2", {"build": workflow_text(install=True, upgrade=False)})
        h.upgrade()
        self.assertEqual(h.hooks(), [("install", "build")])

    def test_an_unchanged_sha_runs_nothing(self):
        h = self._added({"build": workflow_text()})
        resp = h.upgrade()
        self.assertFalse(resp.changed)
        self.assertEqual(h.runner.calls, [])

    def test_a_failing_upgrade_leaves_the_previous_sha_and_drops_the_new_version(self):
        h = self._added({"build": workflow_text()})
        h.remote("sha2", {"build": workflow_text()})
        h.runner.program("upgrade", HookResult(exit_code=2, output="bad"))
        with self.assertRaises(WorkflowSourceError) as caught:
            h.upgrade()
        self.assertIn("upgrade hook exited 2: bad", str(caught.exception))
        self.assertEqual(h.source.read_registry("acme").current, "sha1")
        self.assertFalse(h.source.has_version("acme", "sha2"))
        self.assertTrue(h.source.has_version("acme", "sha1"))

    def test_a_failing_install_on_upgrade_removes_the_data_dir_it_created(self):
        h = self._added({"build": workflow_text()})
        h.remote("sha2", {"build": workflow_text(), "ship": workflow_text(upgrade=False)})
        h.runner.program("install", HookResult(exit_code=1, output="x"))
        with self.assertRaises(WorkflowSourceError):
            h.upgrade()
        self.assertNotIn("/data/workflow-data/acme/ship", h.runner.dirs)

    def test_one_failing_origin_does_not_stop_the_others(self):
        h = Harness()
        for origin in ("one", "two", "three"):
            manifest = 'name = "%s"\ncontract = 1\nrequires-engine = ">=0.1.0"\n' % origin
            h.source.add_remote(origin, manifest, "a", steps=STEPS, workflows={"w": workflow_text()},
                                scripts=ALL_SCRIPTS)
            AddWorkflowSourceUseCase(
                h.source, h.store, h.config, FsAdapter(h.config), h.lifecycle
            ).execute(url=origin, ref="main", name=None)
        h.runner.calls.clear()
        for origin in ("one", "two", "three"):
            manifest = 'name = "%s"\ncontract = 1\nrequires-engine = ">=0.1.0"\n' % origin
            h.source.add_remote(origin, manifest, "b", steps=STEPS, workflows={"w": workflow_text()},
                                scripts=ALL_SCRIPTS)
        h.runner.program("upgrade", HookResult(exit_code=1, output="no"), workflow="two/w")
        resp = UpgradeWorkflowSourcesUseCase(
            h.source, h.store, h.config, FsAdapter(h.config), h.lifecycle).execute()
        self.assertEqual(sorted(r.origin for r in resp.results), ["one", "three"])
        self.assertEqual([f.origin for f in resp.failures], ["two"])
        self.assertIn("two/w", resp.failures[0].error)
        self.assertEqual(h.source.read_registry("two").current, "a")
        self.assertEqual(h.source.read_registry("one").current, "b")


class TestRemoveAndPurge(unittest.TestCase):
    def _added(self):
        h = Harness()
        h.remote("sha1", {"build": workflow_text(), "ship": workflow_text()})
        h.add()
        return h

    def test_remove_keeps_the_data_dirs_and_reports_them(self):
        h = self._added()
        resp = RemoveWorkflowSourceUseCase(h.source, h.store, h.lifecycle).execute("acme")
        self.assertEqual(
            resp.kept_data_dirs,
            ["/data/workflow-data/acme/build", "/data/workflow-data/acme/ship"])
        self.assertEqual(len(h.runner.dirs), 2)

    def test_purge_removes_one_workflow_or_the_whole_origin(self):
        h = self._added()
        purge = PurgeWorkflowDataUseCase(h.lifecycle)
        self.assertEqual(
            purge.execute("acme", "build").removed, ["/data/workflow-data/acme/build"])
        self.assertEqual(h.runner.dirs, {"/data/workflow-data/acme/ship"})
        self.assertEqual(purge.execute("acme").removed, ["/data/workflow-data/acme/ship"])
        self.assertEqual(h.runner.dirs, set())

    def test_purge_refuses_a_name_that_is_not_a_single_segment(self):
        h = self._added()
        purge = PurgeWorkflowDataUseCase(h.lifecycle)
        for bad in ("../x", "a/b", "..", ""):
            with self.assertRaises(WorkflowSourceError):
                purge.execute(bad)
            with self.assertRaises(WorkflowSourceError):
                purge.execute("acme", bad)
        self.assertEqual(len(h.runner.dirs), 2)
