import os
import tempfile
import unittest

from lightcycle.adapters.fsio import FsAdapter
from lightcycle.adapters.scaffold import ScaffoldAdapter
from lightcycle.application.workflows.add import AddWorkflowSourceUseCase
from lightcycle.application.workflows.init_origin import InitWorkflowOriginUseCase
from lightcycle.config import ConfigError
from lightcycle.domain.workflows.contract import ENGINE_CONTRACT
from lightcycle.application.workflows.set_writable import SetOriginWritableUseCase
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

    def write_registry(self, origin, url, ref, current, writable):
        self.registries[origin] = OriginRegistration(url=url, ref=ref, current=current, writable=writable)

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
    def __init__(self, retention=3, projects_root="/projects", version="0.6.319"):
        self._version = version
        self._retention = retention
        self._projects_root = projects_root
        self.personal_origin_set = None

    def workflow_retention(self):
        return self._retention

    def version(self):
        return self._version

    def projects_root(self):
        return self._projects_root

    def set_personal_origin(self, name):
        self.personal_origin_set = name


class _PruneFailingSource(FakeSource):
    def list_versions(self, origin):
        raise OSError("disk unreadable")


class _WriteFailsOnceSource(FakeSource):
    def __init__(self):
        super().__init__()
        self.write_failures = 1

    def write_registry(self, origin, url, ref, current, writable):
        if self.write_failures:
            self.write_failures -= 1
            raise OSError("disk full")
        super().write_registry(origin, url, ref, current, writable)


class _RetentionRaisesConfig(FakeConfig):
    def workflow_retention(self):
        raise ConfigError("workflow-retention is not set")


class _FetchCountingSource(FakeSource):
    def __init__(self):
        super().__init__()
        self.fetches = 0

    def fetch(self, url, ref):
        self.fetches += 1
        return super().fetch(url, ref)


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

    def test_malformed_bundle_line_raises_and_registers_nothing(self):
        source = FakeSource()
        source.add_remote(
            "u", 'name = "acme"\ncontract = 1\n', "sha1",
            workflows={"build": "entry: build\n\ndisposition:\n  merged completed extra\n"})
        with self.assertRaises(WorkflowSourceError) as caught:
            _add(source).execute(url="u", ref="main", name=None)
        self.assertIn("line 4", str(caught.exception))
        self.assertEqual(source.list_origins(), [])

    def test_malformed_hook_occurrence_raises_and_registers_nothing(self):
        source = FakeSource()
        source.add_remote(
            "u", 'name = "acme"\ncontract = 1\n', "sha1",
            steps={"code": _step_text({"model": "x", "step": "code"})},
            workflows={"build": "entry: code\n\nhooks:\n  ci_failed_cap  code\n"})
        with self.assertRaises(WorkflowSourceError) as caught:
            _add(source).execute(url="u", ref="main", name=None)
        message = str(caught.exception)
        self.assertIn("ci_failed_cap", message)
        self.assertIn("code", message)
        self.assertIn("1 token", message)
        self.assertIn("4", message)
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

    def test_restarted_list_raises_and_registers_nothing(self):
        source = FakeSource()
        source.add_remote(
            "u", 'name = "acme"\ncontract = 1\n', "sha1",
            steps={"code": _step_text(
                {"model": "x", "step": "code"}, "1. a\n2. b\n\n1. c")},
            workflows={"build": "entry: code\n"})
        with self.assertRaises(WorkflowSourceError) as caught:
            _add(source).execute(url="u", ref="main", name=None)
        self.assertIn("steps/code.md line 8: top-level list item 1 follows 2", str(caught.exception))
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

    def test_add_never_prunes_the_version_it_just_registered_at_zero_retention(self):
        source = FakeSource()
        cfg = FakeConfig(retention=0)
        source.add_remote("u", 'name = "acme"\ncontract = 1\n', "sha1")
        resp = AddWorkflowSourceUseCase(source, FakeStore(), cfg, FsAdapter(cfg)).execute(
            url="u", ref="main", name=None)
        self.assertEqual(resp.pruned, [])
        self.assertTrue(source.has_version("acme", "sha1"))


class TestAddCommitOrdering(unittest.TestCase):
    def test_clean_run_reports_no_prune_error(self):
        source = FakeSource()
        source.add_remote("u", 'name = "acme"\ncontract = 1\n', "sha1")
        resp = _add(source).execute(url="u", ref="main", name=None)
        self.assertIsNone(resp.prune_error)

    def test_config_error_leaves_nothing_registered_and_fetches_nothing(self):
        source = _FetchCountingSource()
        source.add_remote("u", 'name = "acme"\ncontract = 1\n', "sha1")
        with self.assertRaises(ConfigError):
            _add(source, config=_RetentionRaisesConfig()).execute(url="u", ref="main", name=None)
        self.assertEqual(source.registries, {})
        self.assertEqual(source.materialized, {})
        self.assertEqual(source.fetches, 0)

    def test_prune_failure_after_the_registry_write_is_reported_not_raised(self):
        source = _PruneFailingSource()
        source.add_remote("u", 'name = "acme"\ncontract = 1\n', "sha1")
        resp = _add(source).execute(url="u", ref="main", name=None)
        self.assertEqual(source.read_registry("acme").current, "sha1")
        self.assertEqual(resp.pruned, [])
        self.assertIn("disk unreadable", resp.prune_error)

    def test_write_registry_failure_after_pin_is_healed_by_rerunning_add(self):
        source = _WriteFailsOnceSource()
        source.add_remote("u", 'name = "acme"\ncontract = 1\n', "sha1")
        with self.assertRaises(OSError):
            _add(source).execute(url="u", ref="main", name=None)
        self.assertIsNone(source.read_registry("acme"))
        resp = _add(source).execute(url="u", ref="main", name=None)
        self.assertEqual(resp.sha, "sha1")
        self.assertEqual(source.read_registry("acme").current, "sha1")
        self.assertEqual(source.materialized["acme"], ["sha1"])


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

    def test_upgrade_refuses_restarted_list_and_leaves_the_current_sha(self):
        source = FakeSource()
        source.add_remote("u", 'name = "acme"\ncontract = 1\n', "sha1")
        _add(source).execute(url="u", ref="main", name=None)
        source.add_remote(
            "u", 'name = "acme"\ncontract = 1\n', "sha2",
            steps={"code": _step_text(
                {"model": "x", "step": "code"}, "1. a\n2. b\n\n1. c")},
            workflows={"build": "entry: code\n"})
        cfg = FakeConfig()
        with self.assertRaises(WorkflowSourceError):
            UpgradeWorkflowSourceUseCase(source, FakeStore(), cfg, FsAdapter(cfg)).execute("acme")
        self.assertEqual(source.read_registry("acme").current, "sha1")

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

    def test_upgrade_never_prunes_the_current_version_at_zero_retention(self):
        source = FakeSource()
        cfg = FakeConfig(retention=0)
        fs = FsAdapter(cfg)
        source.add_remote("u", 'name = "acme"\ncontract = 1\n', "sha1")
        AddWorkflowSourceUseCase(source, FakeStore(), cfg, fs).execute(
            url="u", ref="main", name=None)
        source.add_remote("u", 'name = "acme"\ncontract = 1\n', "sha2")
        UpgradeWorkflowSourceUseCase(source, FakeStore(), cfg, fs).execute("acme")
        self.assertEqual(source.read_registry("acme").current, "sha2")
        self.assertEqual(source.materialized["acme"], ["sha2"])


class TestWritable(unittest.TestCase):
    def _added(self, writable=None):
        source = FakeSource()
        source.add_remote("u", 'name = "acme"\ncontract = 1\n', "sha1")
        kwargs = {} if writable is None else {"writable": writable}
        _add(source).execute(url="u", ref="main", name=None, **kwargs)
        return source

    def test_add_defaults_to_read_only(self):
        self.assertFalse(self._added().read_registry("acme").writable)

    def test_add_writable_stores_true(self):
        self.assertTrue(self._added(True).read_registry("acme").writable)

    def _upgrade(self, source):
        source.add_remote("u", 'name = "acme"\ncontract = 1\n', "sha2")
        cfg = FakeConfig()
        UpgradeWorkflowSourceUseCase(source, FakeStore(), cfg, FsAdapter(cfg)).execute("acme")

    def test_upgrade_keeps_a_writable_origin_writable(self):
        source = self._added(True)
        self._upgrade(source)
        self.assertEqual(source.read_registry("acme").current, "sha2")
        self.assertTrue(source.read_registry("acme").writable)

    def test_upgrade_keeps_a_legacy_registration_read_only(self):
        source = self._added()
        source.registries["acme"] = OriginRegistration("u", "main", "sha1")
        self._upgrade(source)
        self.assertFalse(source.read_registry("acme").writable)

    def test_set_flips_only_the_flag(self):
        source = self._added()
        before = source.read_registry("acme")
        SetOriginWritableUseCase(source).execute("acme", True)
        after = source.read_registry("acme")
        self.assertTrue(after.writable)
        self.assertEqual((after.url, after.ref, after.current), (before.url, before.ref, before.current))
        SetOriginWritableUseCase(source).execute("acme", False)
        self.assertFalse(source.read_registry("acme").writable)

    def test_set_unknown_origin_is_refused_naming_registered_ones(self):
        source = self._added()
        with self.assertRaises(WorkflowSourceError) as e:
            SetOriginWritableUseCase(source).execute("nope", True)
        self.assertIn("acme", str(e.exception))

    def test_set_with_none_registered_says_so(self):
        with self.assertRaises(WorkflowSourceError) as e:
            SetOriginWritableUseCase(FakeSource()).execute("nope", True)
        self.assertIn("none registered", str(e.exception))

    def test_set_leaves_the_other_origin_untouched(self):
        source = self._added(True)
        source.registries["other"] = OriginRegistration("o", "", "s", False)
        SetOriginWritableUseCase(source).execute("other", True)
        SetOriginWritableUseCase(source).execute("acme", False)
        self.assertFalse(source.read_registry("acme").writable)
        self.assertTrue(source.read_registry("other").writable)

    def test_list_reports_the_flag_per_origin(self):
        source = self._added(True)
        source.registries["other"] = OriginRegistration("o", "", "s", False)
        views = {v.name: v for v in ListWorkflowSourcesUseCase(source, FakeStore()).execute().origins}
        self.assertTrue(views["acme"].writable)
        self.assertFalse(views["other"].writable)


class TestUpgradeCommitOrdering(unittest.TestCase):
    def _registered(self, source):
        source.add_remote("u", 'name = "acme"\ncontract = 1\n', "sha1")
        _add(source).execute(url="u", ref="main", name=None)
        source.add_remote("u", 'name = "acme"\ncontract = 1\n', "sha2")

    def test_clean_run_reports_no_prune_error(self):
        source = FakeSource()
        self._registered(source)
        cfg = FakeConfig()
        resp = UpgradeWorkflowSourceUseCase(source, FakeStore(), cfg, FsAdapter(cfg)).execute("acme")
        self.assertIsNone(resp.prune_error)

    def test_config_error_leaves_the_prior_registration_and_fetches_nothing(self):
        source = _FetchCountingSource()
        self._registered(source)
        fetches_before = source.fetches
        cfg = _RetentionRaisesConfig()
        with self.assertRaises(ConfigError):
            UpgradeWorkflowSourceUseCase(source, FakeStore(), cfg, FsAdapter(cfg)).execute("acme")
        self.assertEqual(source.read_registry("acme").current, "sha1")
        self.assertEqual(source.materialized["acme"], ["sha1"])
        self.assertEqual(source.fetches, fetches_before)

    def test_prune_failure_after_the_registry_write_is_reported_not_raised(self):
        source = _PruneFailingSource()
        self._registered(source)
        cfg = FakeConfig()
        resp = UpgradeWorkflowSourceUseCase(source, FakeStore(), cfg, FsAdapter(cfg)).execute("acme")
        self.assertEqual(source.read_registry("acme").current, "sha2")
        self.assertEqual(resp.pruned, [])
        self.assertIn("disk unreadable", resp.prune_error)


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


class TestEngineRequirement(unittest.TestCase):
    def _manifest(self, name, requirement):
        extra = 'requires-engine = "%s"\n' % requirement if requirement else ""
        return 'name = "%s"\ncontract = 1\n%s' % (name, extra)

    def test_add_refuses_unmet_requirement_naming_both_versions_and_pins_nothing(self):
        source = FakeSource()
        source.add_remote("u", self._manifest("acme", ">=0.7.0"), "sha1")
        with self.assertRaises(WorkflowSourceError) as ctx:
            _add(source, config=FakeConfig(version="0.6.319")).execute(
                url="u", ref="main", name=None)
        self.assertIn(">=0.7.0", str(ctx.exception))
        self.assertIn("0.6.319", str(ctx.exception))
        self.assertEqual(source.materialized, {})
        self.assertEqual(source.registries, {})

    def test_add_accepts_met_and_absent_requirements(self):
        for name, requirement in (("met", ">=0.6.318,<0.7.0"), ("absent", None)):
            source = FakeSource()
            source.add_remote("u", self._manifest(name, requirement), "sha1")
            resp = _add(source, config=FakeConfig(version="0.6.319")).execute(
                url="u", ref="main", name=None)
            self.assertEqual(resp.origin, name)

    def test_upgrade_refuses_unmet_requirement_and_keeps_the_registry(self):
        source = FakeSource()
        source.add_remote("u", self._manifest("acme", None), "sha1")
        _add(source).execute(url="u", ref="main", name=None)
        source.add_remote("u", self._manifest("acme", ">=0.7.0"), "sha2")
        cfg = FakeConfig(version="0.6.319")
        with self.assertRaises(WorkflowSourceError) as ctx:
            UpgradeWorkflowSourceUseCase(source, FakeStore(), cfg, FsAdapter(cfg)).execute("acme")
        self.assertIn(">=0.7.0", str(ctx.exception))
        self.assertEqual(source.registries["acme"].current, "sha1")
        self.assertFalse(source.has_version("acme", "sha2"))

    def test_upgrade_all_reports_the_unmet_origin_and_upgrades_the_others(self):
        source = FakeSource()
        for name in ("one", "two", "three"):
            source.add_remote("u-" + name, self._manifest(name, None), "sha1")
            _add(source).execute(url="u-" + name, ref="main", name=None)
        source.add_remote("u-one", self._manifest("one", None), "sha2")
        source.add_remote("u-two", self._manifest("two", ">=9.0.0"), "sha2")
        source.add_remote("u-three", self._manifest("three", ">=0.6.0"), "sha2")
        cfg = FakeConfig(version="0.6.319")
        resp = UpgradeWorkflowSourcesUseCase(source, FakeStore(), cfg, FsAdapter(cfg)).execute()
        self.assertEqual(sorted(r.origin for r in resp.results), ["one", "three"])
        self.assertEqual([f.origin for f in resp.failures], ["two"])
        self.assertIn(">=9.0.0", resp.failures[0].error)


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

    def test_missing_identity_refuses_before_creating_the_directory(self):
        root = tempfile.mkdtemp()
        cfg = FakeConfig(projects_root=root)
        git = FakeGit(missing_identity=["user.name", "user.email"])
        with self.assertRaises(WorkflowSourceError) as caught:
            InitWorkflowOriginUseCase(
                cfg, git, FakeSource(), FakeStore(), ScaffoldAdapter(), FsAdapter(cfg)
            ).execute("acme")
        self.assertIn('git config --global user.name "<name>"', str(caught.exception))
        self.assertIn('git config --global user.email "<email>"', str(caught.exception))
        self.assertFalse(os.path.exists(os.path.join(root, "acme")))
        self.assertNotIn("init_repo", [c[0] for c in git.calls])

    def test_failed_scaffold_commit_refuses_naming_the_directory(self):
        root = tempfile.mkdtemp()
        project_dir = os.path.join(root, "acme")
        cfg = FakeConfig(projects_root=root)
        with self.assertRaises(WorkflowSourceError) as caught:
            InitWorkflowOriginUseCase(
                cfg, FakeGit(commit_ok=False), FakeSource(), FakeStore(),
                ScaffoldAdapter(), FsAdapter(cfg)
            ).execute("acme")
        self.assertIn(project_dir, str(caught.exception))
        self.assertIsNone(cfg.personal_origin_set)

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
        self.assertTrue(source.read_registry("acme").writable)
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
