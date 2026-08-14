import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest import mock

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
    def __init__(self, config):
        self.config = config


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

    def test_edit_execs_configured_editor_on_config_path(self):
        c = _cfg()
        cli.set_container(FakeContainer(c))
        with mock.patch("lightcycle.cli.os.execvp") as m:
            call(cli.cmd_config, "--edit")
        m.assert_called_once_with("vi", ["vi", c.config_path()])


if __name__ == "__main__":
    unittest.main()
