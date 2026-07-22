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
        "projects: %s\nspecs: %s\nshortcode: xy\ndefault-workflow: standard\n"
        % (projects, projects)
    )
    config = Config(environ={"LC_HOME": root, "LC_CONFIG": str(cfg)})
    return config, FsAdapter(config), projects


class TestInitProject(unittest.TestCase):
    def test_registers_the_project_shortcode_in_the_central_map(self):
        config, fs, projects = _env()
        r = InitProjectUseCase(config, fs).execute(InitProjectInput(project="myproj"))
        self.assertEqual(r.shortcode, "MYPROJ")
        self.assertTrue(r.changed)
        self.assertEqual(config.project_shortcodes()["myproj"], "MYPROJ")
        self.assertFalse((Path(projects) / "myproj").exists())

    def test_is_idempotent(self):
        config, fs, _ = _env()
        uc = InitProjectUseCase(config, fs)
        uc.execute(InitProjectInput(project="myproj"))
        r = uc.execute(InitProjectInput(project="myproj"))
        self.assertFalse(r.changed)
        self.assertEqual(r.shortcode, "MYPROJ")

    def test_refuses_when_store_not_initialised(self):
        config, fs, _ = _env(with_store=False)
        with self.assertRaises(UseCaseError):
            InitProjectUseCase(config, fs).execute(InitProjectInput(project="myproj"))

    def test_registers_a_project_whose_repo_does_not_exist_on_disk(self):
        config, fs, _ = _env()
        r = InitProjectUseCase(config, fs).execute(InitProjectInput(project="ghost"))
        self.assertEqual(r.shortcode, "GHOST")
        self.assertTrue(r.changed)

    def test_explicit_shortcode_overrides_and_is_idempotent_when_repeated(self):
        config, fs, _ = _env()
        uc = InitProjectUseCase(config, fs)
        uc.execute(InitProjectInput(project="myproj"))
        r = uc.execute(InitProjectInput(project="myproj", shortcode="CUSTOM"))
        self.assertTrue(r.changed)
        self.assertEqual(r.shortcode, "CUSTOM")
        r2 = uc.execute(InitProjectInput(project="myproj", shortcode="CUSTOM"))
        self.assertFalse(r2.changed)
