import tempfile
import unittest
from pathlib import Path

from lightcycle.adapters.fsio import FsAdapter
from lightcycle.application.errors import UseCaseError
from lightcycle.application.setup import InitProjectInput, InitProjectUseCase
from lightcycle.config import Config


def _env(with_store=True, with_workflows=True):
    root = tempfile.mkdtemp()
    projects = tempfile.mkdtemp()
    if with_store:
        Path(root, "store.db").touch()
    if with_workflows:
        Path(root, "workflows").mkdir()
    cfg = Path(tempfile.mkdtemp()) / "config"
    cfg.write_text(
        "projects: %s\nspecs: %s\nshortcode: tg\ndefault-workflow: standard\n"
        % (projects, projects)
    )
    config = Config(environ={"LC_ROOT_OVERRIDE": root, "LC_CONFIG": str(cfg)})
    Path(projects, "myproj").mkdir()
    return config, FsAdapter(config), projects


class TestInitProject(unittest.TestCase):
    def test_scaffolds_the_dot_grid_surface(self):
        config, fs, projects = _env()
        r = InitProjectUseCase(config, fs).execute(InitProjectInput(project="myproj"))
        grid = Path(projects) / "myproj" / ".lightcycle"
        self.assertTrue((grid / "workflows").is_dir())
        self.assertIn("shortcode: MYPROJ", (grid / "config").read_text())
        self.assertIn("scratch-", (grid / ".gitignore").read_text())
        self.assertEqual(set(r.created), {"workflows/", "config", ".gitignore"})

    def test_is_idempotent(self):
        config, fs, _ = _env()
        uc = InitProjectUseCase(config, fs)
        uc.execute(InitProjectInput(project="myproj"))
        self.assertEqual(uc.execute(InitProjectInput(project="myproj")).created, [])

    def test_refuses_when_store_not_initialised(self):
        config, fs, _ = _env(with_store=False)
        with self.assertRaises(UseCaseError):
            InitProjectUseCase(config, fs).execute(InitProjectInput(project="myproj"))

    def test_refuses_unknown_project(self):
        config, fs, _ = _env()
        with self.assertRaises(UseCaseError):
            InitProjectUseCase(config, fs).execute(InitProjectInput(project="ghost"))
