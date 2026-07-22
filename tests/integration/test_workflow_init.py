import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from lightcycle.adapters.fsio import FsAdapter
from lightcycle.adapters.gitio import GitAdapter
from lightcycle.adapters.workflow_source import WorkflowSourceAdapter
from lightcycle.application.workflows.errors import WorkflowSourceError
from lightcycle.application.workflows.init_origin import InitWorkflowOriginUseCase

_GIT_IDENTITY_ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@t",
}


class FakeStore:
    def all_nodes(self):
        return []


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


if __name__ == "__main__":
    unittest.main()
