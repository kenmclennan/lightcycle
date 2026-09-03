import tempfile
import unittest
from pathlib import Path

from lightcycle.adapters.sqlite_store import SqliteStore
from lightcycle.config import Config


def _config():
    root = tempfile.mkdtemp()
    projects = tempfile.mkdtemp()
    cfg = Path(tempfile.mkdtemp()) / "config"
    cfg.write_text(
        "projects: %s\nspecs: %s\nshortcode: xy\ndefault-workflow: standard\n"
        % (projects, projects)
    )
    config = Config(environ={"LC_HOME": root, "LC_CONFIG": str(cfg)})
    return config, projects


class TestProjectShortcode(unittest.TestCase):
    def test_steps_nest_under_the_item_id(self):
        config, projects = _config()
        store = SqliteStore(config)
        store.add_project("acme/horde", shortcode="HORDE")
        item = store.create_item("x", "a description", project="horde", shortcode="HORDE")
        step = store.create_step("s", parent=item)
        self.assertTrue(step.startswith(item + "."), step)

    def test_top_level_item_uses_the_projects_shortcode(self):
        config, projects = _config()
        store = SqliteStore(config)
        store.add_project("acme/horde", shortcode="HORDE")
        iid = store.create_item("x", "a description", project="horde", shortcode="HORDE")
        self.assertTrue(iid.startswith("HORDE-"), iid)

    def test_top_level_item_without_an_explicit_shortcode_uses_the_global_shortcode(self):
        config, projects = _config()
        iid = SqliteStore(config).create_item("y", "a description", project="plain")
        self.assertTrue(iid.startswith("xy-"), iid)

    def test_top_level_item_with_no_project_uses_global_shortcode(self):
        config, _ = _config()
        iid = SqliteStore(config).create_item("z", "a description")
        self.assertTrue(iid.startswith("xy-"), iid)

    def test_a_step_ignores_the_projects_shortcode_and_takes_its_items_namespace(self):
        config, projects = _config()
        store = SqliteStore(config)
        store.add_project("acme/horde", shortcode="HORDE")
        item = store.create_item("x", "a description")
        step = store.create_step("s", parent=item)
        self.assertTrue(step.startswith(item + "."), step)

    def test_projects_with_different_shortcodes_get_independent_counters(self):
        config, projects = _config()
        store = SqliteStore(config)
        store.add_project("acme/horde", shortcode="HORDE")
        store.add_project("acme/saga", shortcode="SAGA")
        horde_first = store.create_item("h1", "a description", project="horde", shortcode="HORDE")
        saga_first = store.create_item("s1", "a description", project="saga", shortcode="SAGA")
        self.assertEqual(horde_first, "HORDE-1")
        self.assertEqual(saga_first, "SAGA-1")
