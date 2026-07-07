import gzip
import os
import tempfile
import unittest
from pathlib import Path

from lightcycle.application.setup import migrate_legacy


class FakeConfig:
    def __init__(self, data_root, legacy_root):
        self._data = data_root
        self._legacy_root = legacy_root

    def data_root(self):
        return self._data

    def legacy_data_root(self):
        return self._legacy_root


def _cfg(*, legacy_store=None, legacy_config=None, legacy_logs=False, legacy_overrides=False, new_store=False):
    data = tempfile.mkdtemp()
    legacy_root = tempfile.mkdtemp()
    if new_store:
        Path(data, "store.db").write_text("new")
    if legacy_store:
        Path(legacy_root, ".grid.db").write_text(legacy_store)
        Path(legacy_root, ".grid.db-wal").write_text("wal")
    if legacy_config:
        Path(legacy_root, "config").write_text(legacy_config)
    if legacy_logs:
        os.makedirs(os.path.join(legacy_root, "logs"))
        Path(legacy_root, "logs", "run.log").write_text("log")
    if legacy_overrides:
        os.makedirs(os.path.join(legacy_root, "steps"))
        Path(legacy_root, "steps", "coder.md").write_text("step")
        os.makedirs(os.path.join(legacy_root, "workflows"))
        Path(legacy_root, "workflows", "standard.md").write_text("flow")
    return FakeConfig(data, legacy_root), data, legacy_root


class TestMigrateLegacy(unittest.TestCase):
    def test_moves_store_and_config_into_data_root(self):
        cfg, data, legacy = _cfg(legacy_store="live-backlog", legacy_config="projects: /x\n")
        resp = migrate_legacy(cfg)
        self.assertEqual(set(resp.moved), {"store", "config"})
        self.assertEqual(Path(data, "store.db").read_text(), "live-backlog")
        self.assertEqual(Path(data, "config").read_text(), "projects: /x\n")
        self.assertFalse(Path(legacy, ".grid.db").exists())

    def test_renames_the_store_file_on_the_way_in(self):
        cfg, data, _ = _cfg(legacy_store="x", legacy_config="y\n")
        migrate_legacy(cfg)
        self.assertTrue(Path(data, "store.db").exists())
        self.assertFalse(Path(data, ".grid.db").exists())

    def test_moves_the_wal_sidecar_too(self):
        cfg, data, _ = _cfg(legacy_store="x", legacy_config="y\n")
        migrate_legacy(cfg)
        self.assertTrue(Path(data, "store.db-wal").exists())

    def test_backs_up_the_store_before_moving(self):
        cfg, data, _ = _cfg(legacy_store="precious", legacy_config="y\n")
        resp = migrate_legacy(cfg)
        self.assertTrue(os.path.exists(resp.backup))
        with gzip.open(resp.backup, "rb") as f:
            self.assertEqual(f.read(), b"precious")

    def test_moves_logs_directory(self):
        cfg, data, _ = _cfg(legacy_store="x", legacy_config="y\n", legacy_logs=True)
        resp = migrate_legacy(cfg)
        self.assertIn("logs", resp.moved)
        self.assertTrue(Path(data, "logs", "run.log").exists())

    def test_moves_override_directories(self):
        cfg, data, _ = _cfg(legacy_store="x", legacy_config="y\n", legacy_overrides=True)
        resp = migrate_legacy(cfg)
        self.assertIn("steps", resp.moved)
        self.assertIn("workflows", resp.moved)
        self.assertTrue(Path(data, "steps", "coder.md").exists())
        self.assertTrue(Path(data, "workflows", "standard.md").exists())

    def test_idempotent_when_new_store_already_exists(self):
        cfg, data, legacy = _cfg(legacy_store="x", legacy_config="y\n", new_store=True)
        resp = migrate_legacy(cfg)
        self.assertTrue(resp.already)
        self.assertEqual(resp.moved, [])
        self.assertTrue(Path(legacy, ".grid.db").exists())

    def test_nothing_to_migrate_on_a_fresh_machine(self):
        cfg, _, _ = _cfg()
        resp = migrate_legacy(cfg)
        self.assertTrue(resp.nothing)
        self.assertEqual(resp.moved, [])
