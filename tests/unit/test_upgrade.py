import unittest

from lightcycle.application.setup.upgrade import (
    VenvBusyError,
    filter_holders,
    format_holders_message,
    parse_process_list,
    parse_remote_version,
    upgrade,
)


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


class TestParseProcessList(unittest.TestCase):
    def test_parses_pid_and_command_per_line(self):
        text = "  123 /venv/bin/python -m lightcycle.pool\n45678 /usr/bin/vim\n"
        self.assertEqual(
            parse_process_list(text),
            [(123, "/venv/bin/python -m lightcycle.pool"), (45678, "/usr/bin/vim")],
        )

    def test_skips_blank_lines(self):
        text = "123 command\n\n   \n456 other\n"
        self.assertEqual(parse_process_list(text), [(123, "command"), (456, "other")])


class TestFilterHolders(unittest.TestCase):
    def setUp(self):
        self.processes = [
            (1, "/venv/bin/python -m lightcycle.pool"),
            (2, "/venv/bin/lc logs -f LC-59.6"),
            (3, "/usr/bin/vim"),
        ]

    def test_matches_processes_whose_command_contains_root(self):
        self.assertEqual(
            filter_holders(self.processes, "/venv", exclude_pid=999),
            [(1, "/venv/bin/python -m lightcycle.pool"), (2, "/venv/bin/lc logs -f LC-59.6")],
        )

    def test_excludes_the_given_pid_even_when_its_command_matches(self):
        self.assertEqual(
            filter_holders(self.processes, "/venv", exclude_pid=1),
            [(2, "/venv/bin/lc logs -f LC-59.6")],
        )

    def test_returns_empty_when_nothing_matches(self):
        self.assertEqual(filter_holders(self.processes, "/no-such-root", exclude_pid=999), [])


class TestFormatHoldersMessage(unittest.TestCase):
    def test_renders_each_holder_and_the_remedy(self):
        message = format_holders_message([(1, "/venv/bin/python -m lightcycle.pool")])
        self.assertIn("1", message)
        self.assertIn("/venv/bin/python -m lightcycle.pool", message)
        self.assertIn("pool", message)
        self.assertIn("lc logs -f", message)


class TestUpgrade(unittest.TestCase):
    def test_upgrades_when_remote_is_newer(self):
        installer = FakeInstaller()
        resp = upgrade(
            "0.1.0", fetch=lambda: "0.2.0", install=installer, installed=lambda: "0.2.0",
            holders=lambda: [])
        self.assertTrue(resp.available)
        self.assertTrue(resp.applied)
        self.assertEqual(installer.calls, 1)
        self.assertEqual(resp.current, "0.1.0")
        self.assertEqual(resp.remote, "0.2.0")

    def test_reports_the_installed_version_not_the_stale_fetched_one(self):
        resp = upgrade(
            "0.1.0", fetch=lambda: "0.2.0", install=lambda: None, installed=lambda: "0.2.1",
            holders=lambda: [])
        self.assertEqual(resp.remote, "0.2.1")

    def test_falls_back_to_fetched_when_installed_version_is_unknown(self):
        resp = upgrade(
            "0.1.0", fetch=lambda: "0.2.0", install=lambda: None, installed=lambda: None,
            holders=lambda: [])
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

    def test_check_only_never_scans_for_venv_holders(self):
        def exploding_holders():
            exploding_holders.calls += 1
            raise AssertionError("holders must not be called on check_only")
        exploding_holders.calls = 0
        upgrade("0.1.0", check_only=True, fetch=lambda: "0.2.0", holders=exploding_holders)
        self.assertEqual(exploding_holders.calls, 0)

    def test_raises_venv_busy_error_when_holders_found_and_does_not_install(self):
        installer = FakeInstaller()
        holders = [(123, "/venv/bin/python -m lightcycle.pool")]
        with self.assertRaises(VenvBusyError):
            upgrade("0.1.0", fetch=lambda: "0.2.0", install=installer, holders=lambda: holders)
        self.assertEqual(installer.calls, 0)


if __name__ == "__main__":
    unittest.main()
