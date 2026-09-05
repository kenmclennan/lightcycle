import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from lightcycle.adapters.fsio import FsAdapter
from lightcycle.adapters.gitio import GitAdapter
from lightcycle.adapters.workflow_source import WorkflowSourceAdapter
from lightcycle.application.workflows.add import AddWorkflowSourceUseCase
from lightcycle.application.workflows.errors import WorkflowSourceError
from lightcycle.application.workflows.init_origin import InitWorkflowOriginUseCase
from lightcycle.config import Config, ConfigError
from tests.support.fake_store import FakeStore

_GIT_IDENTITY_ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@t",
}


class FakeConfig:
    def __init__(self, projects_root, data_root):
        self._projects_root = projects_root
        self._data_root = data_root
        self.personal_origin_set = None

    def projects_root(self):
        return self._projects_root

    def data_root(self):
        return self._data_root

    def workflow_retention(self):
        return 5

    def set_personal_origin(self, name):
        self.personal_origin_set = name


def _use_case():
    projects_root = tempfile.mkdtemp()
    config = FakeConfig(projects_root, tempfile.mkdtemp())
    source = WorkflowSourceAdapter(config)
    fs = FsAdapter(config)
    return InitWorkflowOriginUseCase(config, GitAdapter(), source, FakeStore(), fs), config, source


class TestInitWorkflowOrigin(unittest.TestCase):
    def test_creates_repo_scaffold_git_inits_and_registers(self):
        use_case, config, source = _use_case()
        with patch.dict(os.environ, _GIT_IDENTITY_ENV):
            resp = use_case.execute("acme")
        project_dir = os.path.join(config.projects_root(), "acme")
        self.assertEqual(resp.project_dir, project_dir)
        self.assertEqual(resp.origin, "acme")

        for fname in ("source.toml", "CLAUDE.md", "README.md"):
            self.assertTrue(os.path.isfile(os.path.join(project_dir, fname)))
        self.assertTrue(os.path.isfile(
            os.path.join(project_dir, ".github", "workflows", "simulate.yml")))

        log = subprocess.run(
            ["git", "-C", project_dir, "log", "--oneline"],
            capture_output=True, text=True, check=True)
        self.assertEqual(len(log.stdout.strip().splitlines()), 1)
        branch = subprocess.run(
            ["git", "-C", project_dir, "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, check=True).stdout.strip()
        self.assertEqual(branch, "main")
        head = subprocess.run(
            ["git", "-C", project_dir, "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True).stdout.strip()
        self.assertEqual(resp.sha, head)

        registry = source.read_registry("acme")
        self.assertEqual(registry["current"], head)
        self.assertEqual(config.personal_origin_set, "acme")

    def test_refuses_when_project_dir_already_exists(self):
        use_case, config, source = _use_case()
        project_dir = os.path.join(config.projects_root(), "acme")
        os.makedirs(project_dir)
        with self.assertRaises(WorkflowSourceError) as cm:
            use_case.execute("acme")
        self.assertIn(project_dir, str(cm.exception))
        self.assertIsNone(source.read_registry("acme"))


def _real_config():
    return Config(environ={
        "LC_CONFIG": os.path.join(tempfile.mkdtemp(), "config"),
        "LC_HOME": tempfile.mkdtemp(),
    })


class TestScaffoldedSimulateYmlSequence(unittest.TestCase):
    def test_add_workflow_source_needs_lc_init_before_it_can_succeed(self):
        use_case, _, _ = _use_case()
        with patch.dict(os.environ, _GIT_IDENTITY_ENV):
            resp = use_case.execute("acme")
        project_dir = resp.project_dir

        config_before_init = _real_config()
        add_before_init = AddWorkflowSourceUseCase(
            WorkflowSourceAdapter(config_before_init), FakeStore(),
            config_before_init, FsAdapter(config_before_init))
        with self.assertRaises(ConfigError) as cm:
            add_before_init.execute(url=project_dir, ref="HEAD", name="ci-bundle")
        self.assertIn("workflow-retention", str(cm.exception))

        config_after_init = _real_config()
        config_after_init.ensure_config()
        add_after_init = AddWorkflowSourceUseCase(
            WorkflowSourceAdapter(config_after_init), FakeStore(),
            config_after_init, FsAdapter(config_after_init))
        resp = add_after_init.execute(url=project_dir, ref="HEAD", name="ci-bundle")
        self.assertEqual(resp.origin, "ci-bundle")


if __name__ == "__main__":
    unittest.main()
