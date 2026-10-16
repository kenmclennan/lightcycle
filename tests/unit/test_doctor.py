import os
import tempfile
import unittest
from pathlib import Path

from lightcycle.application.inspect import DoctorInput, DoctorUseCase
from lightcycle.config import _SEED_KEYS, Config
from lightcycle.ports.workflow_bundle import StepPrompt
from lightcycle.ports.workflow_source import OriginRegistration
from tests.support.fake_fs import FakeFs
from tests.support.fake_git import FakeGit
from tests.support.fake_machine import FakeMachine
from tests.support.fake_store import FakeStore
from tests.support.tui_harness import FakeConfigReloadStatus, FakeGuidanceSyncStatus, FakeLock


def _cfg(**filevals):
    p = os.path.join(tempfile.mkdtemp(), "config")
    Path(p).write_text("".join("%s: %s\n" % (k.replace("_", "-"), v) for k, v in filevals.items()))
    return Config(environ={"LC_CONFIG": p})


_ALL_KEYS = {k.replace("-", "_"): v for k, v in _SEED_KEYS}
_ALL_KEYS.update(
    projects="/p",
    default_origin="acme",
    workflows_remote="git@y",
    backups_dir="/b",
    trusted_authors="operator",
)


class FakeWorkflowSource:
    def __init__(self):
        self.materialized = {}
        self.manifests = {}
        self.currents = {}
        self.registries = {}
        self.failures = {}

    def add_bundle(self, origin, sha, contract, current=False, requires=None):
        self.materialized.setdefault(origin, []).append(sha)
        extra = "" if requires is None else 'requires-engine = "%s"\n' % requires
        self.manifests[(origin, sha)] = 'name = "%s"\ncontract = %d\n%s' % (origin, contract, extra)
        if current:
            self.currents[origin] = sha

    def register_origin(self, name, url=None, ref="", current=None):
        self.registries[name] = OriginRegistration(url=url or name, ref=ref, current=current)

    def fail_resolve(self, name, reason):
        self.failures[self.registries[name].url] = reason

    def has_version(self, origin, sha):
        return sha in self.materialized.get(origin, [])

    def workflow_names(self, origin, sha):
        return []

    def pinned_bundle(self, origin, sha):
        return (origin, sha)

    def read_manifest(self, bundle):
        return self.manifests[bundle]

    def current_sha(self, origin):
        return self.currents.get(origin)

    def list_origins(self):
        return sorted(self.registries)

    def read_registry(self, name):
        return self.registries.get(name)

    def unresolvable_reason(self, url, ref):
        return self.failures.get(url)


class FakeWorkflowBundle:
    def __init__(self, bodies=None, errors=None):
        self.bodies = bodies or {}
        self.errors = errors or {}
        self.parsed_roots = []

    def step_roles(self, root):
        return sorted(self.bodies.get(root, {}))

    def parse_step(self, role, root):
        self.parsed_roots.append(root)
        if role in self.errors:
            raise ValueError(self.errors[role])
        roots = root if isinstance(root, list) else [root]
        body = next(
            (self.bodies[r][role] for r in roots if role in self.bodies.get(r, {})), None)
        return None if body is None else StepPrompt(meta={}, body=body)


class _Worktrees:
    def __init__(self, paths=None):
        self._paths = paths or {}

    def worktree_path(self, node):
        return self._paths[node.item]


def _uc(store, source, config, bundle):
    return DoctorUseCase(
        store, source, config, bundle, FakeFs(), FakeMachine(), _Worktrees(),
        FakeGit(), FakeGuidanceSyncStatus(), FakeConfigReloadStatus(), FakeLock(running=False))


class TestAllKeysCoversEverySeedKey(unittest.TestCase):
    def test_all_keys_covers_every_seed_key(self):
        self.assertEqual(set(_ALL_KEYS), {k.replace("-", "_") for k, _ in _SEED_KEYS})


class TestDoctorEngineRequirement(unittest.TestCase):
    def _report(self, requires, version="0.6.319"):
        source = FakeWorkflowSource()
        source.add_bundle("acme", "sha1", 1, current=True, requires=requires)
        source.register_origin("acme", current="sha1")
        config = _cfg(**_ALL_KEYS)
        config.version = lambda: version
        return _uc(FakeStore(), source, config, FakeWorkflowBundle()).execute(DoctorInput())

    def test_unmet_requirement_lands_in_contract(self):
        report = self._report(">=0.7.0")
        messages = [p.message for p in report.problems["contract"]]
        self.assertEqual(len(messages), 1)
        self.assertIn("acme", messages[0])
        self.assertIn("sha1", messages[0])
        self.assertIn(">=0.7.0", messages[0])
        self.assertIn("0.6.319", messages[0])

    def test_malformed_requirement_lands_in_contract(self):
        report = self._report(">=0.7")
        self.assertEqual(len(report.problems["contract"]), 1)
        self.assertIn("requires-engine", report.problems["contract"][0].message)

    def test_met_and_absent_requirements_report_nothing(self):
        for requires in (">=0.6.0", None):
            self.assertEqual(self._report(requires).problems["contract"], [])


class TestDoctorUseCase(unittest.TestCase):
    def test_clean_store_and_healthy_config_reports_healthy(self):
        store = FakeStore()
        source = FakeWorkflowSource()
        source.add_bundle("acme", "sha1", 1, current=True)
        config = _cfg(**_ALL_KEYS)
        report = _uc(store, source, config, FakeWorkflowBundle()).execute(DoctorInput())
        self.assertTrue(report.healthy())
        for problems in report.problems.values():
            self.assertEqual(problems, [])

    def test_pin_missing_on_disk_reports_pins_problem_and_skips_contract(self):
        store = FakeStore()
        item = store.create_item("item", "a description", workflow="acme/build@sha-gone")
        store.update_state(item, "in_progress")
        source = FakeWorkflowSource()
        config = _cfg(**_ALL_KEYS)
        report = _uc(store, source, config, FakeWorkflowBundle()).execute(DoctorInput())
        self.assertFalse(report.healthy())
        self.assertEqual(len(report.problems["pins"]), 1)
        self.assertIn(item, report.problems["pins"][0].node_id)
        self.assertEqual(report.problems["contract"], [])

    def test_resolvable_pin_with_mismatched_contract_reports_contract_problem(self):
        store = FakeStore()
        item = store.create_item("item", "a description", workflow="acme/build@sha1")
        store.update_state(item, "in_progress")
        source = FakeWorkflowSource()
        source.add_bundle("acme", "sha1", 99)
        config = _cfg(**_ALL_KEYS)
        report = _uc(store, source, config, FakeWorkflowBundle()).execute(DoctorInput())
        self.assertFalse(report.healthy())
        self.assertEqual(report.problems["pins"], [])
        self.assertEqual(len(report.problems["contract"]), 1)
        problem = report.problems["contract"][0]
        self.assertIn("99", problem.message)
        self.assertIn("1", problem.message)

    def test_pin_differs_from_current_but_bodies_identical_reports_no_pins_problem(self):
        store = FakeStore()
        item = store.create_item("item", "a description", workflow="acme/build@sha1")
        store.update_state(item, "in_progress")
        source = FakeWorkflowSource()
        source.add_bundle("acme", "sha1", 1)
        source.add_bundle("acme", "sha2", 1, current=True)
        bundle = FakeWorkflowBundle({
            ("acme", "sha1"): {"write-code": "same body"},
            ("acme", "sha2"): {"write-code": "same body"},
        })
        config = _cfg(**_ALL_KEYS)
        report = _uc(store, source, config, bundle).execute(DoctorInput())
        self.assertEqual(report.problems["pins"], [])

    def test_pin_differs_from_current_with_differing_step_body_reports_pins_problem(self):
        store = FakeStore()
        item = store.create_item("item", "a description", workflow="acme/build@sha1")
        store.update_state(item, "in_progress")
        source = FakeWorkflowSource()
        source.add_bundle("acme", "sha1", 1)
        source.add_bundle("acme", "sha2", 1, current=True)
        bundle = FakeWorkflowBundle({
            ("acme", "sha1"): {"write-code": "old body"},
            ("acme", "sha2"): {"write-code": "new body"},
        })
        config = _cfg(**_ALL_KEYS)
        report = _uc(store, source, config, bundle).execute(DoctorInput())
        self.assertEqual(len(report.problems["pins"]), 1)
        problem = report.problems["pins"][0]
        self.assertEqual(problem.node_id, item)
        self.assertIn("acme/build@sha1", problem.message)
        self.assertIn("acme/build@sha2", problem.message)
        self.assertIn("write-code", problem.message)

    def test_step_role_present_in_one_bundle_absent_in_other_counts_as_changed(self):
        store = FakeStore()
        item = store.create_item("item", "a description", workflow="acme/build@sha1")
        store.update_state(item, "in_progress")
        source = FakeWorkflowSource()
        source.add_bundle("acme", "sha1", 1)
        source.add_bundle("acme", "sha2", 1, current=True)
        bundle = FakeWorkflowBundle({
            ("acme", "sha1"): {"write-code": "body"},
            ("acme", "sha2"): {"write-code": "body", "review-code": "new step"},
        })
        config = _cfg(**_ALL_KEYS)
        report = _uc(store, source, config, bundle).execute(DoctorInput())
        self.assertEqual(len(report.problems["pins"]), 1)
        self.assertIn("review-code", report.problems["pins"][0].message)

    def test_drift_check_parses_steps_with_the_engine_fragments_root(self):
        store = FakeStore()
        item = store.create_item("item", "a description", workflow="acme/build@sha1")
        store.update_state(item, "in_progress")
        source = FakeWorkflowSource()
        source.add_bundle("acme", "sha1", 1)
        source.add_bundle("acme", "sha2", 1, current=True)
        bundle = FakeWorkflowBundle({
            ("acme", "sha1"): {"write-code": "body"},
            ("acme", "sha2"): {"write-code": "body"},
        })
        config = _cfg(**_ALL_KEYS)
        _uc(store, source, config, bundle).execute(DoctorInput())
        self.assertTrue(bundle.parsed_roots)
        for roots in bundle.parsed_roots:
            self.assertEqual(roots[0], config.prompts_root())

    def test_unparseable_step_reports_pins_problem_instead_of_raising(self):
        store = FakeStore()
        item = store.create_item("item", "a description", workflow="acme/build@sha1")
        store.update_state(item, "in_progress")
        source = FakeWorkflowSource()
        source.add_bundle("acme", "sha1", 1)
        source.add_bundle("acme", "sha2", 1, current=True)
        bundle = FakeWorkflowBundle(
            {("acme", "sha1"): {"write-code": "body"}, ("acme", "sha2"): {"write-code": "body"}},
            errors={"write-code": "fragment 'plain-language' included by steps/write-code.md not found"},
        )
        config = _cfg(**_ALL_KEYS)
        report = _uc(store, source, config, bundle).execute(DoctorInput())
        self.assertFalse(report.healthy())
        self.assertEqual(len(report.problems["pins"]), 1)
        problem = report.problems["pins"][0]
        self.assertEqual(problem.node_id, item)
        self.assertIn("plain-language", problem.message)

    def test_current_sha_none_reports_no_drift_problem(self):
        store = FakeStore()
        item = store.create_item("item", "a description", workflow="acme/build@sha1")
        store.update_state(item, "in_progress")
        source = FakeWorkflowSource()
        source.add_bundle("acme", "sha1", 1)
        bundle = FakeWorkflowBundle({("acme", "sha1"): {"write-code": "body"}})
        config = _cfg(**_ALL_KEYS)
        report = _uc(store, source, config, bundle).execute(DoctorInput())
        self.assertEqual(report.problems["pins"], [])

    def test_current_sha_not_on_disk_reports_no_drift_problem(self):
        store = FakeStore()
        item = store.create_item("item", "a description", workflow="acme/build@sha1")
        store.update_state(item, "in_progress")
        source = FakeWorkflowSource()
        source.add_bundle("acme", "sha1", 1)
        source.currents["acme"] = "sha-pruned"
        bundle = FakeWorkflowBundle({("acme", "sha1"): {"write-code": "body"}})
        config = _cfg(**_ALL_KEYS)
        report = _uc(store, source, config, bundle).execute(DoctorInput())
        self.assertEqual(report.problems["pins"], [])

    def test_contract_incompatible_and_content_drifted_produce_both_problems(self):
        store = FakeStore()
        item = store.create_item("item", "a description", workflow="acme/build@sha1")
        store.update_state(item, "in_progress")
        source = FakeWorkflowSource()
        source.add_bundle("acme", "sha1", 99)
        source.add_bundle("acme", "sha2", 1, current=True)
        bundle = FakeWorkflowBundle({
            ("acme", "sha1"): {"write-code": "old body"},
            ("acme", "sha2"): {"write-code": "new body"},
        })
        config = _cfg(**_ALL_KEYS)
        report = _uc(store, source, config, bundle).execute(DoctorInput())
        self.assertEqual(len(report.problems["contract"]), 1)
        self.assertEqual(len(report.problems["pins"]), 1)

    def test_drift_check_is_per_item_not_per_origin_pair(self):
        store = FakeStore()
        drifted = store.create_item("item", "a description", workflow="acme/build@sha1")
        store.update_state(drifted, "in_progress")
        clean = store.create_item("item", "another description", workflow="acme/build@sha2")
        store.update_state(clean, "in_progress")
        source = FakeWorkflowSource()
        source.add_bundle("acme", "sha1", 1)
        source.add_bundle("acme", "sha2", 1)
        source.add_bundle("acme", "sha3", 1, current=True)
        bundle = FakeWorkflowBundle({
            ("acme", "sha1"): {"write-code": "old body"},
            ("acme", "sha2"): {"write-code": "same body"},
            ("acme", "sha3"): {"write-code": "same body"},
        })
        config = _cfg(**_ALL_KEYS)
        report = _uc(store, source, config, bundle).execute(DoctorInput())
        self.assertEqual(len(report.problems["pins"]), 1)
        self.assertEqual(report.problems["pins"][0].node_id, drifted)

    def test_default_origin_set_but_unpulled_reports_origin_problem(self):
        store = FakeStore()
        source = FakeWorkflowSource()
        config = _cfg(**_ALL_KEYS)
        report = _uc(store, source, config, FakeWorkflowBundle()).execute(DoctorInput())
        self.assertFalse(report.healthy())
        self.assertEqual(len(report.problems["origin"]), 1)
        self.assertIn("acme", report.problems["origin"][0].message)

    def test_registered_origin_with_resolvable_ref_reports_no_origin_problem(self):
        store = FakeStore()
        source = FakeWorkflowSource()
        source.add_bundle("acme", "sha1", 1, current=True)
        source.register_origin("acme", ref="main")
        config = _cfg(**_ALL_KEYS)
        report = _uc(store, source, config, FakeWorkflowBundle()).execute(DoctorInput())
        self.assertEqual(report.problems["origin"], [])

    def test_registered_origin_with_deleted_ref_reports_origin_problem(self):
        store = FakeStore()
        source = FakeWorkflowSource()
        source.add_bundle("acme", "sha1", 1, current=True)
        source.register_origin("acme", ref="gone-branch")
        source.fail_resolve("acme", "ref 'gone-branch' no longer resolves against acme")
        config = _cfg(**_ALL_KEYS)
        report = _uc(store, source, config, FakeWorkflowBundle()).execute(DoctorInput())
        self.assertEqual(len(report.problems["origin"]), 1)
        problem = report.problems["origin"][0]
        self.assertIn("acme", problem.message)
        self.assertIn("gone-branch", problem.message)

    def test_registered_origin_unreachable_reports_distinguishable_message(self):
        store = FakeStore()
        source = FakeWorkflowSource()
        source.add_bundle("acme", "sha1", 1, current=True)
        source.register_origin("acme", ref="main")
        source.fail_resolve("acme", "acme is not reachable right now")
        config = _cfg(**_ALL_KEYS)
        report = _uc(store, source, config, FakeWorkflowBundle()).execute(DoctorInput())
        self.assertEqual(len(report.problems["origin"]), 1)
        message = report.problems["origin"][0].message
        self.assertIn("not reachable", message)
        self.assertNotIn("no longer resolves", message)

    def test_only_the_failing_origin_among_two_is_reported(self):
        store = FakeStore()
        source = FakeWorkflowSource()
        source.add_bundle("acme", "sha1", 1, current=True)
        source.register_origin("acme", ref="main")
        source.register_origin("other", ref="gone-branch")
        source.fail_resolve("other", "ref 'gone-branch' no longer resolves against other")
        config = _cfg(**_ALL_KEYS)
        report = _uc(store, source, config, FakeWorkflowBundle()).execute(DoctorInput())
        self.assertEqual(len(report.problems["origin"]), 1)
        self.assertIn("other", report.problems["origin"][0].message)

    def test_unpulled_default_origin_and_separate_resolvable_registered_origin_coexist(self):
        store = FakeStore()
        source = FakeWorkflowSource()
        source.register_origin("other", ref="main")
        config = _cfg(**_ALL_KEYS)
        report = _uc(store, source, config, FakeWorkflowBundle()).execute(DoctorInput())
        self.assertEqual(len(report.problems["origin"]), 1)
        self.assertIn("acme", report.problems["origin"][0].message)

    def test_default_origin_missing_from_config_reports_no_origin_problem(self):
        keys = dict(_ALL_KEYS)
        del keys["default_origin"]
        store = FakeStore()
        source = FakeWorkflowSource()
        config = _cfg(**keys)
        report = _uc(store, source, config, FakeWorkflowBundle()).execute(DoctorInput())
        self.assertEqual(report.problems["origin"], [])
        self.assertTrue(any("default-origin" in p.message for p in report.problems["config"]))

    def test_missing_required_config_key_reports_config_problem(self):
        keys = dict(_ALL_KEYS)
        del keys["max_agents"]
        store = FakeStore()
        source = FakeWorkflowSource()
        source.add_bundle("acme", "sha1", 1, current=True)
        config = _cfg(**keys)
        report = _uc(store, source, config, FakeWorkflowBundle()).execute(DoctorInput())
        self.assertFalse(report.healthy())
        self.assertTrue(any("max-agents" in p.message for p in report.problems["config"]))

    def test_obsolete_config_key_reports_config_problem(self):
        keys = dict(_ALL_KEYS)
        keys["retro_interval_items"] = "5"
        store = FakeStore()
        source = FakeWorkflowSource()
        source.add_bundle("acme", "sha1", 1, current=True)
        config = _cfg(**keys)
        report = _uc(store, source, config, FakeWorkflowBundle()).execute(DoctorInput())
        self.assertFalse(report.healthy())
        found = [p for p in report.problems["config"] if "retro-interval-items" in p.message]
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].kind, "config-key-obsolete")
        self.assertEqual(
            found[0].fix,
            'delete the "retro-interval-items:" line with lc config --edit; '
            'this version does not read it')

    def test_all_seed_keys_reports_no_obsolete_key_problems(self):
        store = FakeStore()
        source = FakeWorkflowSource()
        source.add_bundle("acme", "sha1", 1, current=True)
        config = _cfg(**_ALL_KEYS)
        self.assertEqual(config.obsolete_config_keys(), ())
        report = _uc(store, source, config, FakeWorkflowBundle()).execute(DoctorInput())
        self.assertEqual(report.problems["config"], [])

    def test_blank_required_key_reports_config_problem_distinct_from_missing_and_obsolete(self):
        keys = dict(_ALL_KEYS)
        keys["workflows_remote"] = ""
        store = FakeStore()
        source = FakeWorkflowSource()
        source.add_bundle("acme", "sha1", 1, current=True)
        config = _cfg(**keys)
        report = _uc(store, source, config, FakeWorkflowBundle()).execute(DoctorInput())
        self.assertFalse(report.healthy())
        problems = report.problems["config"]
        self.assertEqual(len(problems), 1)
        self.assertIn("workflows-remote", problems[0].message)
        self.assertIn("blank", problems[0].message)
        self.assertEqual(problems[0].kind, "config-key-blank")
        self.assertIn("lc config --edit", problems[0].fix)

    def _blank_problem(self, **blank):
        keys = dict(_ALL_KEYS)
        keys.update(blank)
        source = FakeWorkflowSource()
        source.add_bundle("acme", "sha1", 1, current=True)
        report = _uc(FakeStore(), source, _cfg(**keys), FakeWorkflowBundle()).execute(DoctorInput())
        (problem,) = report.problems["config"]
        return problem

    def test_blank_trusted_authors_fix_names_what_it_does(self):
        problem = self._blank_problem(trusted_authors="")
        self.assertEqual(problem.kind, "config-key-blank")
        self.assertIn("PR comments", problem.fix)
        self.assertIn("trusted-authors: <github-login>", problem.fix)

    def test_blank_workflows_remote_has_its_own_fix(self):
        problem = self._blank_problem(workflows_remote="")
        self.assertIn("workflows-remote: <git url>", problem.fix)
        self.assertNotIn("PR comments", problem.fix)

    def test_blank_unlisted_key_gets_the_generic_fix(self):
        problem = self._blank_problem(backups_dir="")
        self.assertEqual(problem.fix, "set it with `lc config --edit`")

    def test_store_integrity_violation_surfaces_under_store(self):
        store = FakeStore()
        item = store.create_step(parent="missing-parent")
        source = FakeWorkflowSource()
        source.add_bundle("acme", "sha1", 1, current=True)
        config = _cfg(**_ALL_KEYS)
        report = _uc(store, source, config, FakeWorkflowBundle()).execute(DoctorInput())
        self.assertFalse(report.healthy())
        self.assertEqual(len(report.problems["store"]), 1)
        self.assertEqual(report.problems["store"][0].node_id, item)


class TestDoctorOrphans(unittest.TestCase):
    def _report(self, store, fs, machine, worktrees):
        source = FakeWorkflowSource()
        source.add_bundle("acme", "sha1", 1, current=True)
        config = _cfg(**_ALL_KEYS)
        return DoctorUseCase(
            store, source, config, FakeWorkflowBundle(), fs, machine, worktrees,
            FakeGit(), FakeGuidanceSyncStatus(), FakeConfigReloadStatus(), FakeLock(running=False)).execute(DoctorInput())

    def test_worktree_matching_a_claimed_items_path_reports_no_problem(self):
        store = FakeStore()
        store.add_project("acme", local_path="/repo")
        item = store.create_item("item", "a description")
        step = store.create_step(parent=item, role="agent")
        store.update_state(step, "in_progress")
        path = "/repo/.worktrees/%s-code" % item
        fs = FakeFs(dirs={"/repo/.worktrees": ["%s-code" % item]})
        report = self._report(store, fs, FakeMachine(), _Worktrees({item: path}))
        self.assertEqual(report.problems["orphans"], [])

    def test_two_claimed_steps_in_different_phases_expect_two_distinct_paths(self):
        store = FakeStore()
        store.add_project("acme", local_path="/repo")
        item = store.create_item("item", "a description")
        code = store.create_step(step="write-code", parent=item, role="agent")
        spec = store.create_step(step="spec-handle-feedback", parent=item, role="agent")
        store.update_state(code, "in_progress")
        store.update_state(spec, "in_progress")
        code_path = "/repo/.worktrees/%s-code" % item
        spec_path = "/repo/.worktrees/%s-spec" % item

        class _ByStage:
            def worktree_path(self, node):
                return {"write-code": code_path, "spec-handle-feedback": spec_path}[node.stage]

        fs = FakeFs(dirs={"/repo/.worktrees": ["%s-code" % item, "%s-spec" % item]})
        machine = FakeMachine(worktree_pids={code_path: [1], spec_path: [2]})
        report = self._report(store, fs, machine, _ByStage())
        self.assertEqual(report.problems["orphans"], [])

    def test_unmatched_worktree_with_live_pids_reports_one_problem_naming_path_and_pids(self):
        store = FakeStore()
        store.add_project("acme", local_path="/repo")
        fs = FakeFs(dirs={"/repo/.worktrees": ["stray-item-code"]})
        machine = FakeMachine(worktree_pids={"/repo/.worktrees/stray-item-code": [111, 222]})
        report = self._report(store, fs, machine, _Worktrees())
        self.assertEqual(len(report.problems["orphans"]), 1)
        problem = report.problems["orphans"][0]
        self.assertIn("/repo/.worktrees/stray-item-code", problem.message)
        self.assertIn("111", problem.message)
        self.assertIn("222", problem.message)

    def test_unmatched_worktree_with_no_live_pids_reports_no_problem(self):
        store = FakeStore()
        store.add_project("acme", local_path="/repo")
        fs = FakeFs(dirs={"/repo/.worktrees": ["idle-item-code"]})
        report = self._report(store, fs, FakeMachine(), _Worktrees())
        self.assertEqual(report.problems["orphans"], [])

    def test_process_in_a_deleted_worktree_reports_one_problem_naming_path_and_pids(self):
        store = FakeStore()
        store.add_project("acme", local_path="/repo")
        fs = FakeFs(dirs={"/repo/.worktrees": []})
        machine = FakeMachine(cwd_pids={
            "/repo/.worktrees/LC-9-change": [41],
            "/repo/.worktrees/LC-9-change/src": [42, 43],
        })
        report = self._report(store, fs, machine, _Worktrees())
        self.assertEqual(len(report.problems["orphans"]), 1)
        message = report.problems["orphans"][0].message
        self.assertIn("/repo/.worktrees/LC-9-change", message)
        for pid in ("41", "42", "43"):
            self.assertIn(pid, message)

    def test_process_in_an_expected_live_worktree_is_not_reported_as_deleted(self):
        store = FakeStore()
        store.add_project("acme", local_path="/repo")
        item = store.create_item("item", "a description")
        step = store.create_step(parent=item, role="agent")
        store.update_state(step, "in_progress")
        path = "/repo/.worktrees/%s-code" % item
        fs = FakeFs(dirs={"/repo/.worktrees": ["%s-code" % item]})
        machine = FakeMachine(cwd_pids={path: [7], path + "/src": [8]})
        report = self._report(store, fs, machine, _Worktrees({item: path}))
        self.assertEqual(report.problems["orphans"], [])

    def test_process_in_an_existing_unexpected_worktree_is_reported_once(self):
        store = FakeStore()
        store.add_project("acme", local_path="/repo")
        fs = FakeFs(dirs={"/repo/.worktrees": ["stray"]})
        machine = FakeMachine(
            worktree_pids={"/repo/.worktrees/stray": [5]},
            cwd_pids={"/repo/.worktrees/stray": [5]},
        )
        report = self._report(store, fs, machine, _Worktrees())
        self.assertEqual(len(report.problems["orphans"]), 1)



class TestDoctorFacets(unittest.TestCase):
    def _problems(self, store, fs, git=None):
        source = FakeWorkflowSource()
        source.add_bundle("acme", "sha1", 1, current=True)
        report = DoctorUseCase(
            store, source, _cfg(**_ALL_KEYS), FakeWorkflowBundle(), fs, FakeMachine(), _Worktrees(),
            git if git is not None else FakeGit(), FakeGuidanceSyncStatus(), FakeConfigReloadStatus(), FakeLock(running=False)).execute(DoctorInput())
        return report.problems["facets"]

    def _kb(self, *pages):
        fs = FakeFs(
            files={"/kb/%s" % p: b"" for p in pages}, dirs={"/kb": ["languages"]},
        )
        git = FakeGit(ref="origin/main", ref_files={"origin/main": {p: b"" for p in pages}})
        store = FakeStore()
        store.add_project("guidance", local_path="/kb")
        return store, fs, git

    def test_both_identities_registered_is_one_problem_with_or_without_facets(self):
        for facets in (None, ("kotlin",)):
            store, fs, git = self._kb("kotlin.md")
            store.add_project("knowledge", local_path="/old")
            if facets:
                store.add_project("acme/x", facets=facets)
            problems = self._problems(store, fs, git)
            self.assertEqual(len(problems), 1)
            self.assertIn("knowledge", problems[0].message)
            self.assertIn("guidance", problems[0].message)

    def test_only_guidance_registered_reports_no_duplicate(self):
        store, fs, git = self._kb()
        self.assertEqual(self._problems(store, fs, git), [])

    def test_no_facets_anywhere_is_clean_with_or_without_a_guidance_repo(self):
        store = FakeStore()
        store.add_project("acme/x")
        self.assertEqual(self._problems(store, FakeFs()), [])
        kb_store, fs, git = self._kb()
        self.assertEqual(self._problems(kb_store, fs, git), [])

    def test_facets_without_a_registered_guidance_repo_is_one_problem(self):
        store = FakeStore()
        store.add_project("acme/x", facets=("kotlin", "spring"))
        problems = self._problems(store, FakeFs())
        self.assertEqual([p.message for p in problems], [
            "facets are declared but no guidance repo is registered - run `lc init`"
        ])

    def test_guidance_repo_registered_without_a_path_is_one_problem(self):
        store = FakeStore()
        store.add_project("guidance")
        store.add_project("acme/x", facets=("kotlin",))
        self.assertEqual(len(self._problems(store, FakeFs())), 1)

    def test_guidance_repo_path_missing_on_disk_is_one_problem(self):
        store = FakeStore()
        store.add_project("guidance", local_path="/kb")
        store.add_project("acme/x", facets=("kotlin", "spring"))
        problems = self._problems(store, FakeFs())
        self.assertEqual([p.message for p in problems], [
            "facets are declared but the guidance repo is missing at /kb - restore it, "
            "or run `lc project rm guidance` then `lc init`"
        ])

    def test_every_facet_with_a_page_is_clean(self):
        store, fs, git = self._kb("languages/kotlin.md", "frameworks/spring.md")
        store.add_project("acme/x", facets=("kotlin", "spring"))
        self.assertEqual(self._problems(store, fs, git), [])

    def test_a_missing_page_names_the_project_and_the_facet_only_for_that_facet(self):
        store, fs, git = self._kb("languages/kotlin.md")
        store.add_project("acme/x", facets=("kotlin", "spring"))
        problems = self._problems(store, fs, git)
        self.assertEqual([p.message for p in problems], [
            "project acme/x declares facet spring but the guidance repo has no concept page "
            "for it - add spring.md under the guidance repo, or remove the facet with "
            "`lc project set acme/x --facets <remaining>`"
        ])
        self.assertIsNone(problems[0].node_id)

    def test_index_md_is_not_a_concept_page(self):
        store, fs, git = self._kb("index.md", "languages/index.md")
        store.add_project("acme/x", facets=("index",))
        self.assertEqual(len(self._problems(store, fs, git)), 1)

    def test_page_match_is_case_sensitive(self):
        store, fs, git = self._kb("CONVENTIONS.md")
        store.add_project("acme/x", facets=("conventions",))
        self.assertEqual(len(self._problems(store, fs, git)), 1)

    def test_a_page_under_a_dot_directory_is_not_found(self):
        store, fs, git = self._kb(".git/kotlin.md")
        store.add_project("acme/x", facets=("kotlin",))
        self.assertEqual(len(self._problems(store, fs, git)), 1)



if __name__ == "__main__":
    unittest.main()

class _ScheduleBundle(FakeWorkflowBundle):
    def __init__(self, known):
        super().__init__()
        self._known = known

    def workflow_text(self, name, root):
        return "" if "%s/%s" % (root, name) in self._known else None

    def workflow_meta(self, name, root):
        return self._known.get("%s/%s" % (root, name), {})


class _ScheduleSource(FakeWorkflowSource):
    def __init__(self, known, origin="acme"):
        super().__init__()
        self._known = known
        self.add_bundle(origin, "sha1", 1, current=True)
        self.register_origin(origin, current="sha1")

    def pinned_bundle(self, origin, sha):
        return origin

    def read_manifest(self, bundle):
        return self.manifests[(bundle, "sha1")]

    def workflow_names(self, origin, sha):
        return [k.split("/", 1)[1] for k in self._known]


class _ScheduleConfig:
    def __init__(self, config, blocks):
        self._config = config
        self._blocks = blocks

    def schedule_blocks(self):
        return self._blocks

    def __getattr__(self, name):
        return getattr(self._config, name)


def _schedule_doctor(blocks, known=None, projects=("acme/app",), origin="acme"):
    store = FakeStore()
    for p in projects:
        store.add_project(p, shortcode="APP")
    known = {"acme/audit": {}} if known is None else known
    config = _ScheduleConfig(_cfg(**_ALL_KEYS), blocks)
    uc = DoctorUseCase(
        store, _ScheduleSource(known, origin), config, _ScheduleBundle(known), FakeFs(),
        FakeMachine(), _Worktrees(), FakeGit(), FakeGuidanceSyncStatus(), FakeConfigReloadStatus(), FakeLock(running=False))
    return uc.execute(DoctorInput())


def _block(**overrides):
    base = {"enabled": "true", "workflow": "acme/audit", "project": "acme/app",
            "cron": "0 9 * * 1", "guard": "materials-changed"}
    base.update(overrides)
    return base


class TestDoctorSchedules(unittest.TestCase):
    def _messages(self, report, category="config"):
        return [p.message for p in report.problems[category]]

    def test_a_schedule_free_config_reports_nothing_new(self):
        self.assertTrue(_schedule_doctor({}).healthy())

    def test_a_sound_schedule_reports_nothing(self):
        self.assertTrue(_schedule_doctor({"weekly": _block()}).healthy())

    def test_each_broken_enabled_schedule_is_flagged_in_config_with_its_id(self):
        cases = {
            "missing-workflow": _block(workflow="acme/ghost"),
            "bad-guard": _block(guard="shell-out"),
            "bad-cron": _block(cron="@daily"),
            "bad-param": _block(guard="pending-reflections", min="x"),
            "bad-project": _block(project="acme/ghost"),
        }
        report = _schedule_doctor(cases)
        messages = self._messages(report)
        for sid in cases:
            with self.subTest(sid):
                self.assertTrue(
                    any(m.startswith("schedule %s: " % sid) for m in messages), messages)

    def test_the_json_category_keys_are_unchanged(self):
        self.assertEqual(
            set(_schedule_doctor({}).problems),
            {"store", "pins", "contract", "origin", "config", "orphans", "facets", "guidance"})

    def test_an_off_schedule_is_not_a_finding(self):
        report = _schedule_doctor({"weekly": _block(enabled="false", guard="shell-out")})
        self.assertEqual(self._messages(report), [])

    def test_a_bundle_suggestion_naming_an_unknown_guard_is_a_contract_finding(self):
        known = {"acme/audit": {"schedule": {"cron": "0 9 * * 1", "guard": "shell-out"}}}
        report = _schedule_doctor({}, known=known)
        messages = self._messages(report, "contract")
        self.assertEqual(len(messages), 1)
        self.assertTrue(messages[0].startswith("schedule acme/audit: "))
        self.assertIn("unknown guard", messages[0])

    def _retired(self, blocks, origin="lightcycle", names=("retro-audit", "material-audit", "daily-summary")):
        suggestion = {"schedule": {"cron": "0 9 * * 1", "guard": "materials-changed"}}
        known = {"%s/%s" % (origin, n): suggestion for n in names}
        report = _schedule_doctor(blocks, known=known, origin=origin)
        return [p for p in report.problems["config"] if p.kind == "schedule-not-enabled"]

    def test_each_retired_job_with_no_block_is_a_schedule_not_enabled_finding(self):
        found = self._retired({})
        self.assertEqual(len(found), 3)
        messages = sorted(p.message for p in found)
        self.assertIn(
            "workflow lightcycle/daily-summary has no schedule block in config; "
            "the engine no longer runs this job itself", messages)
        self.assertIn("lc schedule list", found[0].fix)
        self.assertIn("upgrade skill", found[0].fix)

    def test_a_block_naming_the_workflow_under_any_id_covers_it(self):
        blocks = {"mine": _block(workflow="lightcycle/retro-audit")}
        found = self._retired(blocks)
        self.assertEqual(
            sorted(p.message.split()[1] for p in found),
            ["lightcycle/daily-summary", "lightcycle/material-audit"])

    def test_a_block_recorded_as_off_still_covers_it(self):
        blocks = {"mine": _block(workflow="lightcycle/retro-audit", enabled="false")}
        self.assertEqual(len(self._retired(blocks)), 2)

    def test_another_origins_suggestion_is_never_reported(self):
        self.assertEqual(self._retired({}, origin="acme"), [])

    def test_another_workflow_of_the_lightcycle_origin_is_never_reported(self):
        self.assertEqual(self._retired({}, names=("audit",)), [])

    def test_a_schedule_block_is_not_reported_as_an_obsolete_key(self):
        config = _cfg(**_ALL_KEYS)
        text = Path(config.config_path()).read_text()
        Path(config.config_path()).write_text(
            text + "schedule-weekly:\n  enabled: false\n  workflow: acme/audit\n")
        config.reload()
        self.assertEqual(config.obsolete_config_keys(), ())

_LIFECYCLE_META = {
    "lifecycle": {"install": "scripts/install.sh"},
    "config": {"api-token": "required"},
    "config-example": {"api-token": "x"},
}


def _lifecycle_doctor(known, config_text="", present=("acme/scripts/install.sh",), executable=None):
    config = _cfg(**_ALL_KEYS)
    path = config.config_path()
    Path(path).write_text(Path(path).read_text() + config_text)
    config.reload()
    fs = FakeFs(
        files={p: b"#!/bin/sh\n" for p in present},
        executable=present if executable is None else executable)
    uc = DoctorUseCase(
        FakeStore(), _ScheduleSource(known), config, _ScheduleBundle(known), fs,
        FakeMachine(), _Worktrees(), FakeGit(), FakeGuidanceSyncStatus(),
        FakeConfigReloadStatus(), FakeLock(running=False))
    return uc.execute(DoctorInput())


class TestDoctorWorkflowLifecycle(unittest.TestCase):
    def _messages(self, report, category):
        return [p.message for p in report.problems[category]]

    def test_a_sound_lifecycle_with_its_config_reports_nothing(self):
        report = _lifecycle_doctor(
            {"acme/build": _LIFECYCLE_META},
            "workflow-acme-build:\n  api-token: tok\n")
        self.assertTrue(report.healthy(), report.problems)

    def test_a_missing_required_key_is_a_config_finding_naming_block_and_key(self):
        report = _lifecycle_doctor({"acme/build": _LIFECYCLE_META})
        messages = self._messages(report, "config")
        self.assertEqual(len(messages), 1)
        self.assertIn("'api-token'", messages[0])
        self.assertIn("'workflow-acme-build'", messages[0])

    def test_a_blank_required_key_is_a_config_finding(self):
        report = _lifecycle_doctor(
            {"acme/build": _LIFECYCLE_META}, "workflow-acme-build:\n  api-token:\n")
        self.assertEqual(len(self._messages(report, "config")), 1)

    def test_an_absent_optional_key_is_not_a_finding(self):
        meta = dict(_LIFECYCLE_META, config={"api-token": "optional"})
        self.assertTrue(_lifecycle_doctor({"acme/build": meta}).healthy())

    def test_a_workflow_dict_block_is_not_reported_obsolete(self):
        report = _lifecycle_doctor(
            {"acme/build": _LIFECYCLE_META},
            "workflow-acme-build:\n  api-token: tok\nworkflow-stray: 1\n")
        messages = self._messages(report, "config")
        self.assertEqual(len(messages), 1)
        self.assertIn("workflow-stray", messages[0])

    def test_a_missing_script_is_a_contract_finding(self):
        report = _lifecycle_doctor(
            {"acme/build": _LIFECYCLE_META}, "workflow-acme-build:\n  api-token: tok\n",
            present=())
        messages = self._messages(report, "contract")
        self.assertEqual(len(messages), 1)
        self.assertIn("acme/build", messages[0])
        self.assertIn("does not exist", messages[0])

    def test_a_script_guard_with_no_script_is_a_contract_finding(self):
        meta = {"schedule": {"cron": "0 * * * *", "guard": "script:scripts/changed.sh"}}

        report = _lifecycle_doctor({"acme/build": meta}, present=())

        messages = self._messages(report, "contract")
        self.assertTrue(any(
            "acme/build" in m and "script guard" in m and "does not exist" in m
            for m in messages), messages)

    def test_a_workflow_with_config_and_no_hooks_still_reports_a_missing_required_key(self):
        meta = {"config": {"api-token": "required"}, "config-example": {"api-token": "x"}}

        report = _lifecycle_doctor({"acme/build": meta}, present=())

        messages = self._messages(report, "config")
        self.assertEqual(len(messages), 1)
        self.assertIn("'api-token'", messages[0])

    def test_two_workflows_mapping_to_one_block_are_a_config_finding(self):
        known = {"acme/b-c": {}, "acme/b": {}}
        source = _ScheduleSource(known)
        source.add_bundle("acme-b", "sha1", 1, current=True)
        source.register_origin("acme-b", current="sha1")
        source.workflow_names = lambda origin, sha: ["c"] if origin == "acme-b" else ["b-c"]
        config = _cfg(**_ALL_KEYS)
        uc = DoctorUseCase(
            FakeStore(), source, config, _ScheduleBundle(known), FakeFs(), FakeMachine(),
            _Worktrees(), FakeGit(), FakeGuidanceSyncStatus(), FakeConfigReloadStatus(),
            FakeLock(running=False))
        messages = [p.message for p in uc.execute(DoctorInput()).problems["config"]]
        self.assertTrue(any("workflow-acme-b-c" in m for m in messages), messages)



class TestReloadProblems(unittest.TestCase):
    def _report(self, state, pid=4242, mtime_matches=True):
        config = _cfg(**_ALL_KEYS)
        if "rejected_mtime" in state and mtime_matches:
            state = dict(state, rejected_mtime=config.config_mtime())
        source = FakeWorkflowSource()
        source.add_bundle("acme", "sha1", 1, current=True)
        return DoctorUseCase(
            FakeStore(), source, config, FakeWorkflowBundle(), FakeFs(), FakeMachine(),
            _Worktrees(), FakeGit(), FakeGuidanceSyncStatus(),
            FakeConfigReloadStatus(dict(state, pid=pid)),
            FakeLock(running=True, pid=4242),
        ).execute(DoctorInput()).problems["config"]

    def _rejected(self, **kw):
        return self._report(
            {"outcome": "rejected", "reason": "bad value", "rejected_mtime": 1,
             "restart_required": []}, **kw)

    def test_a_rejection_by_the_running_pool_is_reported(self):
        problems = self._rejected()
        self.assertEqual(len(problems), 1)
        self.assertIn("config edit rejected by the running pool (bad value)", problems[0].message)
        self.assertIn("last good config", problems[0].message)

    def test_a_rejection_is_dropped_once_the_file_changed_again(self):
        self.assertEqual(self._rejected(mtime_matches=False), [])

    def test_a_status_from_another_pid_is_ignored(self):
        self.assertEqual(self._rejected(pid=99), [])

    def test_restart_required_keys_are_reported(self):
        problems = self._report(
            {"outcome": "reloaded", "rejected_mtime": None,
             "restart_required": ["poll-seconds", "spin-cap"]})
        self.assertEqual(
            [p.message for p in problems],
            ["running pool needs a restart for: poll-seconds, spin-cap"])
