import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from lightcycle.application.setup.upgrade import filter_holders, scan_venv_holders

ROOT = Path(__file__).resolve().parents[2]
LC = str(ROOT / "bin" / "lc")


def _run(args):
    home, xdg = tempfile.mkdtemp(), tempfile.mkdtemp()
    env = dict(os.environ, LC_HOME=home, XDG_CONFIG_HOME=xdg)
    env.pop("LC_CONFIG", None)
    result = subprocess.run([sys.executable, LC] + args, capture_output=True, text=True, env=env)
    return result, home


class TestUpgradeCommand(unittest.TestCase):
    def test_check_is_store_less_and_exits_cleanly(self):
        result, home = _run(["upgrade", "--check"])
        self.assertFalse(
            os.path.exists(os.path.join(home, "store.db")),
            "upgrade --check must run before the store is built",
        )
        self.assertIn(
            result.returncode,
            (0, 1),
            "expected a clean exit (0 checked, 1 network error), got:\n%s" % result.stderr,
        )


class TestFilterHolders(unittest.TestCase):
    def test_matches_a_process_whose_command_contains_a_signature(self):
        processes = [(11, "/opt/py/python -m lightcycle.adapters.worker_session"), (12, "/bin/zsh")]
        holders = filter_holders(processes, ["-m lightcycle"], exclude_pid=1)
        self.assertEqual([(11, "/opt/py/python -m lightcycle.adapters.worker_session")], holders)

    def test_returns_exactly_the_matching_processes_from_a_mix(self):
        processes = [
            (11, "/opt/py/python -m lightcycle.adapters.worker_session"),
            (12, "/bin/zsh"),
            (13, "/usr/bin/vim"),
        ]
        holders = filter_holders(processes, ["-m lightcycle"], exclude_pid=1)
        self.assertEqual([(11, "/opt/py/python -m lightcycle.adapters.worker_session")], holders)

    def test_excludes_the_given_pid_even_when_its_command_matches(self):
        processes = [(11, "/opt/py/python -m lightcycle.adapters.worker_session")]
        self.assertEqual([], filter_holders(processes, ["-m lightcycle"], exclude_pid=11))


class TestScanVenvHolders(unittest.TestCase):
    def test_never_reports_the_scanning_process_as_a_holder(self):
        holders = scan_venv_holders()
        self.assertNotIn(os.getpid(), [pid for pid, _ in holders])

    def test_reports_a_re_execd_worker_process_via_the_module_invocation_shape(self):
        line = (
            "4242 /opt/homebrew/Cellar/python@3.14/3.14.6/Frameworks/Python.framework/"
            "Versions/3.14/Resources/Python.app/Contents/MacOS/Python "
            "-m lightcycle.adapters.worker_session"
        )
        holders = scan_venv_holders(list_processes=lambda: line)
        self.assertEqual([4242], [pid for pid, _ in holders])

    def test_reports_a_console_script_invocation_via_the_entry_point_shape(self):
        bindir = os.path.dirname(os.path.abspath(sys.argv[0]))
        line = "4343 %s/lc --version" % bindir
        holders = scan_venv_holders(list_processes=lambda: line)
        self.assertEqual([4343], [pid for pid, _ in holders])


if __name__ == "__main__":
    unittest.main()
