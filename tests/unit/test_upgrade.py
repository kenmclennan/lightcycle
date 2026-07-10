import unittest

from lightcycle.application.setup.upgrade import parse_remote_version, upgrade


class FakeInstaller:
    def __init__(self):
        self.calls = 0

    def __call__(self):
        self.calls += 1


class TestParseRemoteVersion(unittest.TestCase):
    def test_extracts_the_version_from_init_source(self):
        self.assertEqual(parse_remote_version('__version__ = "1.2.3"\n'), "1.2.3")

    def test_returns_none_when_no_version_line(self):
        self.assertIsNone(parse_remote_version("no version here\n"))


class TestUpgrade(unittest.TestCase):
    def test_upgrades_when_remote_is_newer(self):
        installer = FakeInstaller()
        resp = upgrade("0.1.0", fetch=lambda: "0.2.0", install=installer, installed=lambda: "0.2.0")
        self.assertTrue(resp.available)
        self.assertTrue(resp.applied)
        self.assertEqual(installer.calls, 1)
        self.assertEqual(resp.current, "0.1.0")
        self.assertEqual(resp.remote, "0.2.0")

    def test_reports_the_installed_version_not_the_stale_fetched_one(self):
        resp = upgrade(
            "0.1.0", fetch=lambda: "0.2.0", install=lambda: None, installed=lambda: "0.2.1")
        self.assertEqual(resp.remote, "0.2.1")

    def test_falls_back_to_fetched_when_installed_version_is_unknown(self):
        resp = upgrade(
            "0.1.0", fetch=lambda: "0.2.0", install=lambda: None, installed=lambda: None)
        self.assertEqual(resp.remote, "0.2.0")

    def test_no_op_when_versions_are_equal(self):
        installer = FakeInstaller()
        resp = upgrade("0.2.0", fetch=lambda: "0.2.0", install=installer)
        self.assertFalse(resp.available)
        self.assertFalse(resp.applied)
        self.assertEqual(installer.calls, 0)

    def test_no_op_when_local_is_ahead(self):
        installer = FakeInstaller()
        resp = upgrade("0.3.0", fetch=lambda: "0.2.0", install=installer)
        self.assertFalse(resp.available)
        self.assertFalse(resp.applied)
        self.assertEqual(installer.calls, 0)

    def test_check_only_reports_without_installing(self):
        installer = FakeInstaller()
        resp = upgrade("0.1.0", check_only=True, fetch=lambda: "0.2.0", install=installer)
        self.assertTrue(resp.available)
        self.assertFalse(resp.applied)
        self.assertEqual(installer.calls, 0)


if __name__ == "__main__":
    unittest.main()
