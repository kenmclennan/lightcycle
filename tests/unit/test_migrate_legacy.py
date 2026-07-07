import gzip
import os
import tempfile
import unittest
from pathlib import Path

from the_grid.application.setup import migrate_legacy


class FakeConfig:
    def __init__(self, data_root, legacy_root, legacy_config):
        self._data = data_root
        self._legacy_root = legacy_root
        self._legacy_config = legacy_config

    def data_root(self):
        return self._data

    def legacy_data_root(self):
        return self._legacy_root

    def legacy_config_path(self):
        return self._legacy_config


def _cfg(*, legacy_store=None, legacy_config=None, legacy_logs=False, new_store=False):
    data = tempfile.mkdtemp()
    legacy_root = tempfile.mkdtemp()
    legacy_config_dir = tempfile.mkdtemp()
    legacy_config_path = os.path.join(legacy_config_dir, "config")
    if new_store:
        Path(data, ".grid.db").write_text("new")
    if legacy_store:
        Path(legacy_root, ".grid.db").write_text(legacy_store)
        Path(legacy_root, ".grid.db-wal").write_text("wal")
    if legacy_config:
        Path(legacy_config_path).write_text(legacy_config)
    if legacy_logs:
        os.makedirs(os.path.join(legacy_root, "logs"))
        Path(legacy_root, "logs", "run.log").write_text("log")
    return FakeConfig(data, legacy_root, legacy_config_path), data, legacy_root


class TestMigrateLegacy(unittest.TestCase):
    def test_moves_store_and_config_into_data_root(self):
        cfg, data, legacy = _cfg(legacy_store="live-backlog", legacy_config="projects: /x\n")
        resp = migrate_legacy(cfg)
        self.assertEqual(set(resp.moved), {"store", "config"})
        self.assertEqual(Path(data, ".grid.db").read_text(), "live-backlog")
        self.assertEqual(Path(data, "config").read_text(), "projects: /x\n")
        self.assertFalse(Path(legacy, ".grid.db").exists())

    def test_moves_the_wal_sidecar_too(self):
        cfg, data, _ = _cfg(legacy_store="x", legacy_config="y\n")
        migrate_legacy(cfg)
        self.assertTrue(Path(data, ".grid.db-wal").exists())

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
