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
        "projects: %s\nspecs: %s\nshortcode: tg\ndefault-workflow: standard\n"
        % (projects, projects)
    )
    config = Config(environ={"LC_HOME": root, "LC_CONFIG": str(cfg)})
    return config, projects


def _project(projects, name, body):
    d = Path(projects) / name / ".lightcycle"
    d.mkdir(parents=True)
    (d / "config").write_text(body)


class TestProjectShortcode(unittest.TestCase):
    def test_epic_id_uses_the_projects_shortcode(self):
        config, projects = _config()
        _project(projects, "horde", "shortcode: HORDE\n")
        eid = SqliteStore(config).create_theme("x", project="horde")
        self.assertTrue(eid.startswith("HORDE-"), eid)

    def test_epic_without_project_config_uses_global_shortcode(self):
        config, projects = _config()
        eid = SqliteStore(config).create_theme("y", project="plain")
        self.assertTrue(eid.startswith("tg-"), eid)

    def test_no_project_uses_global_shortcode(self):
        config, _ = _config()
        eid = SqliteStore(config).create_theme("z")
        self.assertTrue(eid.startswith("tg-"), eid)

    def test_stories_nest_under_the_epic_id(self):
        config, projects = _config()
        _project(projects, "horde", "shortcode: HORDE\n")
        store = SqliteStore(config)
        theme = store.create_theme("x", project="horde")
        item = store.create_item("s", theme=theme)
        self.assertTrue(item.startswith(theme + "."), item)


class TestProjectDefaultWorkflow(unittest.TestCase):
    def test_project_default_workflow_overrides_global(self):
        config, projects = _config()
        _project(projects, "bdd", "default-workflow: gherkin\n")
        self.assertEqual(config.default_workflow_for("bdd"), "gherkin")

    def test_falls_back_to_global_default(self):
        config, _ = _config()
        self.assertEqual(config.default_workflow_for("plain"), "standard")
