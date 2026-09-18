import os
import tempfile
import unittest
from pathlib import Path

from lightcycle.application.inspect import DoctorInput, DoctorUseCase
from lightcycle.config import _SEED_KEYS, Config
from lightcycle.ports.workflow_bundle import StepPrompt
from lightcycle.ports.workflow_source import OriginRegistration
from tests.support.fake_fs import FakeFs
from tests.support.fake_machine import FakeMachine
from tests.support.fake_store import FakeStore


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
)


class FakeWorkflowSource:
    def __init__(self):
        self.materialized = {}
        self.manifests = {}
        self.currents = {}
        self.registries = {}
        self.failures = {}

    def add_bundle(self, origin, sha, contract, current=False):
        self.materialized.setdefault(origin, []).append(sha)
        self.manifests[(origin, sha)] = 'name = "%s"\ncontract = %d\n' % (origin, contract)
        if current:
            self.currents[origin] = sha

    def register_origin(self, name, url=None, ref=""):
        self.registries[name] = OriginRegistration(url=url or name, ref=ref, current=None)

    def fail_resolve(self, name, reason):
        self.failures[self.registries[name].url] = reason

    def has_version(self, origin, sha):
        return sha in self.materialized.get(origin, [])

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
    def __init__(self, bodies=None):
        self.bodies = bodies or {}

    def step_roles(self, root):
        return sorted(self.bodies.get(root, {}))

    def parse_step(self, role, root):
        body = self.bodies.get(root, {}).get(role)
        return None if body is None else StepPrompt(meta={}, body=body)


class _Worktrees:
    def __init__(self, paths=None):
        self._paths = paths or {}

    def worktree_path(self, item):
        return self._paths[item]


def _uc(store, source, config, bundle):
    return DoctorUseCase(
        store, source, config, bundle, FakeFs(), FakeMachine(), _Worktrees(),
    )


class TestAllKeysCoversEverySeedKey(unittest.TestCase):
    def test_all_keys_covers_every_seed_key(self):
        self.assertEqual(set(_ALL_KEYS), {k.replace("-", "_") for k, _ in _SEED_KEYS})


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
        self.assertTrue(any("retro-interval-items" in p.message for p in report.problems["config"]))

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
        ).execute(DoctorInput())

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


if __name__ == "__main__":
    unittest.main()
