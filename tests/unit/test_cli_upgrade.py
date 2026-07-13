import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from lightcycle.application.setup import VenvBusyError
from lightcycle.cli import cmd_upgrade


class TestCmdUpgrade(unittest.TestCase):
    def test_reports_already_at_latest_when_no_newer_version(self):
        with patch("lightcycle.cli.upgrade") as fake_upgrade:
            fake_upgrade.return_value.available = False
            fake_upgrade.return_value.applied = False
            fake_upgrade.return_value.current = "0.2.0"
            fake_upgrade.return_value.remote = "0.2.0"
            out = io.StringIO()
            with redirect_stdout(out):
                rc = cmd_upgrade([]) or 0
        self.assertEqual(rc, 0)
        self.assertIn("already at latest (0.2.0)", out.getvalue())

    def test_check_reports_availability_without_installing(self):
        with patch("lightcycle.cli.upgrade") as fake_upgrade:
            fake_upgrade.return_value.available = True
            fake_upgrade.return_value.applied = False
            fake_upgrade.return_value.current = "0.2.0"
            fake_upgrade.return_value.remote = "0.3.0"
            out = io.StringIO()
            with redirect_stdout(out):
                rc = cmd_upgrade(["--check"]) or 0
            self.assertEqual(fake_upgrade.call_args.kwargs["check_only"], True)
        self.assertEqual(rc, 0)
        self.assertIn("upgrade available: 0.2.0 -> 0.3.0", out.getvalue())

    def test_upgrades_and_reports_the_move(self):
        with patch("lightcycle.cli.upgrade") as fake_upgrade:
            fake_upgrade.return_value.available = True
            fake_upgrade.return_value.applied = True
            fake_upgrade.return_value.current = "0.2.0"
            fake_upgrade.return_value.remote = "0.3.0"
            out = io.StringIO()
            with redirect_stdout(out):
                rc = cmd_upgrade([]) or 0
            self.assertEqual(fake_upgrade.call_args.kwargs["check_only"], False)
        self.assertEqual(rc, 0)
        self.assertIn("upgraded: 0.2.0 -> 0.3.0", out.getvalue())

    def test_refuses_and_prints_the_holders_message_when_venv_is_busy(self):
        with patch("lightcycle.cli.upgrade") as fake_upgrade:
            fake_upgrade.side_effect = VenvBusyError([(123, "/venv/bin/python -m lightcycle.pool")])
            err = io.StringIO()
            with redirect_stderr(err):
                rc = cmd_upgrade([]) or 0
        self.assertEqual(rc, 1)
        self.assertIn("/venv/bin/python -m lightcycle.pool", err.getvalue())


if __name__ == "__main__":
    unittest.main()
