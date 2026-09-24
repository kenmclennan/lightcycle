import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

from lightcycle import cli
from lightcycle.config import _SEED_KEYS, Config


def call(fn, *args):
    out, err = io.StringIO(), io.StringIO()
    try:
        with redirect_stdout(out), redirect_stderr(err):
            rc = fn(list(args)) or 0
    except SystemExit as e:
        rc = e.code if isinstance(e.code, int) else 1
    return rc, out.getvalue(), err.getvalue()


class FakeContainer:
    def __init__(self, config, launcher=None):
        self.config = config
        self.launcher = launcher


class FakeLauncher:
    def __init__(self, returncode=0, touches=False):
        self.returncode = returncode
        self.touches = touches
        self.edited = None

    def edit(self, editor, path):
        self.edited = (editor, path)
        if self.touches:
            st = os.stat(path).st_mtime_ns + 1_000_000_000
            os.utime(path, ns=(st, st))
        return self.returncode


def _cfg():
    d = tempfile.mkdtemp()
    return Config(environ={"LC_CONFIG": os.path.join(d, "config")})


class TestCmdConfig(unittest.TestCase):
    def setUp(self):
        self._orig = cli.container()
        self.addCleanup(lambda: cli.set_container(self._orig))

    def test_prints_all_resolved_keys_not_just_projects_and_specs(self):
        c = _cfg()
        c.ensure_config()
        cli.set_container(FakeContainer(c))
        rc, out, err = call(cli.cmd_config)
        self.assertEqual(rc, 0, err)
        for key, _default in _SEED_KEYS:
            self.assertIn(key, out)

    def test_personal_origin_missing_reports_unset_without_init_hint(self):
        c = _cfg()
        c.ensure_config()
        text = Path(c.config_path()).read_text()
        text = "\n".join(
            line for line in text.splitlines() if not line.startswith("personal-origin:")
        ) + "\n"
        Path(c.config_path()).write_text(text)
        cli.set_container(FakeContainer(c))
        rc, out, err = call(cli.cmd_config)
        self.assertEqual(rc, 0, err)
        self.assertIn("personal-origin: (not set)", out)
        self.assertNotIn("personal-origin: (not set - run `lc init`)", out)

    def test_value_left_at_the_seed_shows_the_seed_not_a_default_claim(self):
        c = _cfg()
        c.ensure_config()
        cli.set_container(FakeContainer(c))
        rc, out, err = call(cli.cmd_config)
        self.assertEqual(rc, 0, err)
        self.assertIn("max-agents: 5 (seed 5)", out)
        self.assertNotIn("(default)", out)

    def test_value_set_away_from_the_seed_still_shows_the_seed(self):
        c = _cfg()
        c.ensure_config()
        text = Path(c.config_path()).read_text()
        text = "\n".join(
            "max-agents: 9" if line.startswith("max-agents:") else line
            for line in text.splitlines()
        ) + "\n"
        Path(c.config_path()).write_text(text)
        cli.set_container(FakeContainer(c))
        rc, out, err = call(cli.cmd_config)
        self.assertEqual(rc, 0, err)
        self.assertIn("max-agents: 9 (seed 5)", out)

    def test_personal_origin_set_shows_no_seed_rather_than_an_empty_one(self):
        c = _cfg()
        c.ensure_config()
        text = Path(c.config_path()).read_text()
        text = "\n".join(
            "personal-origin: mine" if line.startswith("personal-origin:") else line
            for line in text.splitlines()
        ) + "\n"
        Path(c.config_path()).write_text(text)
        cli.set_container(FakeContainer(c))
        rc, out, err = call(cli.cmd_config)
        self.assertEqual(rc, 0, err)
        self.assertIn("personal-origin: mine (no seed)", out)

    def test_out_of_range_value_shows_rejected_not_not_set(self):
        c = _cfg()
        c.ensure_config()
        text = Path(c.config_path()).read_text()
        text = "\n".join(
            "max-agents: -1" if line.startswith("max-agents:") else line
            for line in text.splitlines()
        ) + "\n"
        Path(c.config_path()).write_text(text)
        cli.set_container(FakeContainer(c))
        rc, out, err = call(cli.cmd_config)
        self.assertEqual(rc, 0, err)
        line = next(l for l in out.splitlines() if l.startswith("max-agents:"))
        self.assertIn("rejected", line)
        self.assertIn("-1", line)
        self.assertNotIn("not set", line)

    def test_env_override_shows_only_the_env_marker_not_a_seed(self):
        c = _cfg()
        c.ensure_config()
        c._environ["LC_MAX_AGENTS"] = "9"
        cli.set_container(FakeContainer(c))
        rc, out, err = call(cli.cmd_config)
        self.assertEqual(rc, 0, err)
        line = next(l for l in out.splitlines() if l.startswith("max-agents:"))
        self.assertEqual(line, "max-agents: 9 (env: LC_MAX_AGENTS)")

    def test_edit_calls_launcher_edit_with_configured_editor_and_config_path(self):
        c = _cfg()
        launcher = FakeLauncher()
        cli.set_container(FakeContainer(c, launcher))
        rc, _out, err = call(cli.cmd_config, "--edit")
        self.assertEqual(rc, 0, err)
        self.assertEqual(launcher.edited, ("vi", c.config_path()))

    def test_edit_returns_the_editors_exit_code(self):
        c = _cfg()
        launcher = FakeLauncher(returncode=1)
        cli.set_container(FakeContainer(c, launcher))
        rc, _out, _err = call(cli.cmd_config, "--edit")
        self.assertEqual(rc, 1)

    def test_edit_that_changed_the_file_says_running_processes_need_a_restart(self):
        c = _cfg()
        cli.set_container(FakeContainer(c, FakeLauncher(touches=True)))
        rc, out, err = call(cli.cmd_config, "--edit")
        self.assertEqual(rc, 0, err)
        self.assertIn("lc start", out)
        self.assertIn("lc tui", out)
        self.assertIn("until restarted", out)

    def test_edit_that_left_the_file_alone_says_nothing_about_restarting(self):
        c = _cfg()
        cli.set_container(FakeContainer(c, FakeLauncher()))
        rc, out, err = call(cli.cmd_config, "--edit")
        self.assertEqual(rc, 0, err)
        self.assertNotIn("restarted", out)

    def test_failed_editor_does_not_claim_a_saved_config(self):
        c = _cfg()
        cli.set_container(FakeContainer(c, FakeLauncher(returncode=1, touches=True)))
        rc, out, _err = call(cli.cmd_config, "--edit")
        self.assertEqual(rc, 1)
        self.assertNotIn("restarted", out)


if __name__ == "__main__":
    unittest.main()
