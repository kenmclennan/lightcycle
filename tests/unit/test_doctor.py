import os
import tempfile
import unittest
from pathlib import Path

from lightcycle.application.inspect import DoctorInput, DoctorUseCase
from lightcycle.config import Config
from tests.support.fake_store import FakeStore


def _cfg(**filevals):
    p = os.path.join(tempfile.mkdtemp(), "config")
    Path(p).write_text("".join("%s: %s\n" % (k.replace("_", "-"), v) for k, v in filevals.items()))
    return Config(environ={"LC_CONFIG": p})


_ALL_KEYS = dict(
    projects="/p", specs="/s", specs_remote="git@x", branch_prefix="feat", shortcode="PROJ",
    default_origin="acme", workflows_remote="git@y", max_agents="5", worktree_retries="6",
    worktree_retry_sleep="0.25", max_boot_seconds="120", max_session_seconds="1800",
    poll_seconds="5", worker_history="20", editor="vi", retro_interval_reflections="20",
    backups_dir="/b", backup_interval_minutes="15", backup_retention="96",
    workflow_retention="5", max_title_length="72", personal_origin="",
    project_shortcodes="",
)


class FakeWorkflowSource:
    def __init__(self):
        self.materialized = {}
        self.manifests = {}
        self.currents = {}

    def add_bundle(self, origin, sha, contract, current=False):
        self.materialized.setdefault(origin, []).append(sha)
        self.manifests[(origin, sha)] = 'name = "%s"\ncontract = %d\n' % (origin, contract)
        if current:
            self.currents[origin] = sha

    def has_version(self, origin, sha):
        return sha in self.materialized.get(origin, [])

    def bundle_path(self, origin, sha):
        return (origin, sha)

    def read_manifest(self, bundle):
        return self.manifests[bundle]

    def current_sha(self, origin):
        return self.currents.get(origin)


class TestDoctorUseCase(unittest.TestCase):
    def test_clean_store_and_healthy_config_reports_healthy(self):
        store = FakeStore()
        source = FakeWorkflowSource()
        source.add_bundle("acme", "sha1", 1, current=True)
        config = _cfg(**_ALL_KEYS)
        report = DoctorUseCase(store, source, config).execute(DoctorInput())
        self.assertTrue(report.healthy())
        for problems in report.problems.values():
            self.assertEqual(problems, [])

    def test_pin_missing_on_disk_reports_pins_problem_and_skips_contract(self):
        store = FakeStore()
        item = store.create_item("item", workflow="acme/build@sha-gone")
        store.update_state(item, "in_progress")
        source = FakeWorkflowSource()
        config = _cfg(**_ALL_KEYS)
        report = DoctorUseCase(store, source, config).execute(DoctorInput())
        self.assertFalse(report.healthy())
        self.assertEqual(len(report.problems["pins"]), 1)
        self.assertIn(item, report.problems["pins"][0].node_id)
        self.assertEqual(report.problems["contract"], [])

    def test_resolvable_pin_with_mismatched_contract_reports_contract_problem(self):
        store = FakeStore()
        item = store.create_item("item", workflow="acme/build@sha1")
        store.update_state(item, "in_progress")
        source = FakeWorkflowSource()
        source.add_bundle("acme", "sha1", 99)
        config = _cfg(**_ALL_KEYS)
        report = DoctorUseCase(store, source, config).execute(DoctorInput())
        self.assertFalse(report.healthy())
        self.assertEqual(report.problems["pins"], [])
        self.assertEqual(len(report.problems["contract"]), 1)
        problem = report.problems["contract"][0]
        self.assertIn("99", problem.message)
        self.assertIn("1", problem.message)

    def test_default_origin_set_but_unpulled_reports_origin_problem(self):
        store = FakeStore()
        source = FakeWorkflowSource()
        config = _cfg(**_ALL_KEYS)
        report = DoctorUseCase(store, source, config).execute(DoctorInput())
        self.assertFalse(report.healthy())
        self.assertEqual(len(report.problems["origin"]), 1)
        self.assertIn("acme", report.problems["origin"][0].message)

    def test_default_origin_missing_from_config_reports_no_origin_problem(self):
        keys = dict(_ALL_KEYS)
        del keys["default_origin"]
        store = FakeStore()
        source = FakeWorkflowSource()
        config = _cfg(**keys)
        report = DoctorUseCase(store, source, config).execute(DoctorInput())
        self.assertEqual(report.problems["origin"], [])
        self.assertTrue(any("default-origin" in p.message for p in report.problems["config"]))

    def test_missing_required_config_key_reports_config_problem(self):
        keys = dict(_ALL_KEYS)
        del keys["max_agents"]
        store = FakeStore()
        source = FakeWorkflowSource()
        source.add_bundle("acme", "sha1", 1, current=True)
        config = _cfg(**keys)
        report = DoctorUseCase(store, source, config).execute(DoctorInput())
        self.assertFalse(report.healthy())
        self.assertTrue(any("max-agents" in p.message for p in report.problems["config"]))

    def test_store_integrity_violation_surfaces_under_store(self):
        store = FakeStore()
        item = store.create_item("item")
        store.edit_node(item, parent="missing-parent")
        source = FakeWorkflowSource()
        source.add_bundle("acme", "sha1", 1, current=True)
        config = _cfg(**_ALL_KEYS)
        report = DoctorUseCase(store, source, config).execute(DoctorInput())
        self.assertFalse(report.healthy())
        self.assertEqual(len(report.problems["store"]), 1)
        self.assertEqual(report.problems["store"][0].node_id, item)


if __name__ == "__main__":
    unittest.main()
