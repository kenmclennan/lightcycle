import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout

from lightcycle import cli
from lightcycle.application.setup.init_grid import InitGridUseCase
from tests.support.fake_fs import FakeFs
from tests.support.fake_git import FakeGit
from tests.support.fake_store import FakeStore
from tests.unit.test_cmd_doctor import FakeConfig as DoctorConfig
from tests.unit.test_cmd_doctor import FakeContainer as DoctorContainer
from tests.unit.test_setup import FakeConfig as InitConfig
from tests.unit.test_setup import FakeGitHub


def call(fn, *args):
    out, err = io.StringIO(), io.StringIO()
    try:
        with redirect_stdout(out), redirect_stderr(err):
            rc = fn(list(args)) or 0
    except SystemExit as e:
        rc = e.code if isinstance(e.code, int) else 1
    return rc, out.getvalue(), err.getvalue()


class _Config(DoctorConfig):
    def __init__(self, shortcode="GDN"):
        self._shortcode = shortcode

    def guidance_shortcode(self):
        return self._shortcode

    def max_title_length(self):
        return 72

    def config_path(self):
        return __file__


class _InitConfig(InitConfig):
    def __init__(self, shortcode):
        super().__init__()
        self._shortcode = shortcode

    def guidance_shortcode(self):
        return self._shortcode


def _init(store, shortcode="GDN"):
    InitGridUseCase(store, FakeFs(), _InitConfig(shortcode), FakeGit(), FakeGitHub()).execute()


def _file_guidance_item():
    return call(
        cli.cmd_new, "item", "A cross-cutting rule", "--description", "a description",
        "--repo", "guidance", "--project", "guidance",
    )


class TestGuidanceShortcodeEndToEnd(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        self.addCleanup(cli.set_container, cli._container)
        cli.set_container(DoctorContainer(self.store, config=_Config()))

    def test_after_init_a_guidance_item_mints_a_gdn_id(self):
        _init(self.store)
        rc, out, err = _file_guidance_item()
        self.assertEqual(rc, 0, err)
        self.assertTrue(out.strip().startswith("GDN-"), out)

    def test_on_a_shortcodeless_store_filing_is_refused_doctor_names_the_fix_and_applying_it_succeeds(self):
        self.store.add_project("guidance", local_path="/kb")
        rc, out, err = _file_guidance_item()
        self.assertEqual(rc, 1)
        self.assertEqual(out, "")
        self.assertEqual(self.store.all_nodes(), [])

        rc, out, err = call(cli.cmd_doctor, "--json")
        self.assertEqual(rc, 1)
        found = [p for p in json.loads(out)["guidance"] if p["kind"] == "guidance-shortcode-missing"]
        self.assertEqual(len(found), 1)
        fix = found[0]["fix"]
        self.assertIn("lc project set guidance --shortcode GDN", fix)

        rc, out, err = call(cli.cmd_project, "set", "guidance", "--shortcode", "GDN")
        self.assertEqual(rc, 0, err)
        rc, out, err = _file_guidance_item()
        self.assertEqual(rc, 0, err)
        self.assertTrue(out.strip().startswith("GDN-"), out)

    def test_init_uses_a_custom_configured_shortcode(self):
        cli.set_container(DoctorContainer(self.store, config=_Config("KB")))
        _init(self.store, "KB")
        self.assertEqual(self.store.get_project("guidance").shortcode, "KB")
        rc, out, err = _file_guidance_item()
        self.assertEqual(rc, 0, err)
        self.assertTrue(out.strip().startswith("KB-"), out)

    def test_the_guidance_identity_may_hold_the_shortcode_and_a_product_project_may_not(self):
        self.store.add_project("guidance", local_path="/kb")
        rc, out, err = call(cli.cmd_project, "add", "acme/x", "--shortcode", "GDN")
        self.assertEqual(rc, 1)
        self.assertIn("guidance project", err)
        self.assertIsNone(self.store.get_project("acme/x"))
        rc, out, err = call(cli.cmd_project, "set", "guidance", "--shortcode", "GDN")
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.store.get_project("guidance").shortcode, "GDN")
