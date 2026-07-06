import tempfile
import unittest
from pathlib import Path

from the_grid.adapters.sqlite_store import SqliteStore
from the_grid.config import Config


def _config():
    root = tempfile.mkdtemp()
    projects = tempfile.mkdtemp()
    cfg = Path(tempfile.mkdtemp()) / "config"
    cfg.write_text(
        "projects: %s\nspecs: %s\nshortcode: tg\ndefault-workflow: standard\n"
        % (projects, projects)
    )
    config = Config(environ={"GRID_ROOT_OVERRIDE": root, "GRID_CONFIG": str(cfg)})
    return config, projects


def _project(projects, name, body):
    d = Path(projects) / name / ".grid"
    d.mkdir(parents=True)
    (d / "config").write_text(body)


class TestProjectShortcode(unittest.TestCase):
    def test_epic_id_uses_the_projects_shortcode(self):
        config, projects = _config()
        _project(projects, "horde", "shortcode: HORDE\n")
        eid = SqliteStore(config).create_epic("x", project="horde")
        self.assertTrue(eid.startswith("HORDE-"), eid)

    def test_epic_without_project_config_uses_global_shortcode(self):
        config, projects = _config()
        eid = SqliteStore(config).create_epic("y", project="plain")
        self.assertTrue(eid.startswith("tg-"), eid)

    def test_no_project_uses_global_shortcode(self):
        config, _ = _config()
        eid = SqliteStore(config).create_epic("z")
        self.assertTrue(eid.startswith("tg-"), eid)

    def test_stories_nest_under_the_epic_id(self):
        config, projects = _config()
        _project(projects, "horde", "shortcode: HORDE\n")
        store = SqliteStore(config)
        epic = store.create_epic("x", project="horde")
        story = store.create_story("s", epic=epic)
        self.assertTrue(story.startswith(epic + "."), story)


class TestProjectDefaultWorkflow(unittest.TestCase):
    def test_project_default_workflow_overrides_global(self):
        config, projects = _config()
        _project(projects, "bdd", "default-workflow: gherkin\n")
        self.assertEqual(config.default_workflow_for("bdd"), "gherkin")

    def test_falls_back_to_global_default(self):
        config, _ = _config()
        self.assertEqual(config.default_workflow_for("plain"), "standard")
