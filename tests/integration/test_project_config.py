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
    def test_epic_id_uses_the_projects_shortcode(self):
        config, projects = _config()
        store = SqliteStore(config)
        store.add_project("acme/horde", shortcode="HORDE")
        eid = store.create_theme("x", project="horde", shortcode="HORDE")
        self.assertTrue(eid.startswith("HORDE-"), eid)

    def test_theme_without_an_explicit_shortcode_uses_the_global_shortcode(self):
        config, projects = _config()
        eid = SqliteStore(config).create_theme("y", project="plain")
        self.assertTrue(eid.startswith("xy-"), eid)

    def test_no_project_uses_global_shortcode(self):
        config, _ = _config()
        eid = SqliteStore(config).create_theme("z")
        self.assertTrue(eid.startswith("xy-"), eid)

    def test_stories_nest_under_the_epic_id(self):
        config, projects = _config()
        store = SqliteStore(config)
        store.add_project("acme/horde", shortcode="HORDE")
        theme = store.create_theme("x", project="horde", shortcode="HORDE")
        item = store.create_item("s", theme=theme)
        self.assertTrue(item.startswith(theme + "."), item)

    def test_top_level_item_uses_the_projects_shortcode(self):
        config, projects = _config()
        store = SqliteStore(config)
        store.add_project("acme/horde", shortcode="HORDE")
        iid = store.create_item("x", project="horde", shortcode="HORDE")
        self.assertTrue(iid.startswith("HORDE-"), iid)

    def test_top_level_item_without_an_explicit_shortcode_uses_the_global_shortcode(self):
        config, projects = _config()
        iid = SqliteStore(config).create_item("y", project="plain")
        self.assertTrue(iid.startswith("xy-"), iid)

    def test_top_level_item_with_no_project_uses_global_shortcode(self):
        config, _ = _config()
        iid = SqliteStore(config).create_item("z")
        self.assertTrue(iid.startswith("xy-"), iid)

    def test_themed_item_ignores_the_projects_shortcode(self):
        config, projects = _config()
        store = SqliteStore(config)
        store.add_project("acme/horde", shortcode="HORDE")
        theme = store.create_theme("x")
        item = store.create_item("s", theme=theme, project="horde")
        self.assertTrue(item.startswith(theme + "."), item)

    def test_projects_with_different_shortcodes_get_independent_counters(self):
        config, projects = _config()
        store = SqliteStore(config)
        store.add_project("acme/horde", shortcode="HORDE")
        store.add_project("acme/saga", shortcode="SAGA")
        horde_first = store.create_item("h1", project="horde", shortcode="HORDE")
        saga_first = store.create_item("s1", project="saga", shortcode="SAGA")
        self.assertEqual(horde_first, "HORDE-1")
        self.assertEqual(saga_first, "SAGA-1")
