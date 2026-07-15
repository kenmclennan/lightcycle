import unittest
from unittest import mock

from lightcycle import cli
from lightcycle.cli import _compose_driver


class _DriverFs:
    def store_ready(self):
        return True

    def read_md(self, relpath, root):
        self.read_args = (relpath, root)
        return {"meta": {"model": "opus"}, "body": "SEAT"}


class _DriverCfg:
    def data_root(self):
        return "/data"

    def prompts_root(self):
        return "/pkg/prompts"


class _DriverContainer:
    def __init__(self):
        self.fs = _DriverFs()
        self.config = _DriverCfg()


class TestCmdDriver(unittest.TestCase):
    def test_reads_driver_md_from_the_prompts_root_and_forwards_extra_flags(self):
        container = _DriverContainer()
        cli.set_container(container)
        captured = {}
        with mock.patch.object(cli.os, "execvp", lambda f, a: captured.update(cmd=a)), \
                mock.patch.object(cli, "_human_step_skills", lambda: []), \
                mock.patch.object(cli, "show_banner", lambda: None):
            cli.cmd_driver(["--resume", "s1"])
        self.assertEqual(container.fs.read_args, ("driver.md", "/pkg/prompts"))
        cmd = captured["cmd"]
        self.assertIn("--model", cmd)
        self.assertIn("opus", cmd)
        self.assertEqual(cmd[-2:], ["--resume", "s1"])

    def test_does_not_force_skip_permissions_but_passes_it_through_when_asked(self):
        cli.set_container(_DriverContainer())
        default_cmd, opted_in = {}, {}
        patches = (
            mock.patch.object(cli, "_human_step_skills", lambda: []),
            mock.patch.object(cli, "show_banner", lambda: None),
        )
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])
        with mock.patch.object(cli.os, "execvp", lambda f, a: default_cmd.update(c=a)):
            cli.cmd_driver([])
        self.assertNotIn("--dangerously-skip-permissions", default_cmd["c"])
        with mock.patch.object(cli.os, "execvp", lambda f, a: opted_in.update(c=a)):
            cli.cmd_driver(["--dangerously-skip-permissions"])
        self.assertIn("--dangerously-skip-permissions", opted_in["c"])


class TestComposeDriver(unittest.TestCase):
    def test_no_skills_returns_base_unchanged(self):
        self.assertEqual(_compose_driver("BASE", []), "BASE")

    def test_appends_each_skill_labelled_by_step(self):
        out = _compose_driver("BASE", [("review-plan", "REVIEW BODY"), ("cleanup", "CLEAN BODY")])
        self.assertIn("BASE", out)
        for marker in ("## review-plan", "REVIEW BODY", "## cleanup", "CLEAN BODY"):
            self.assertIn(marker, out)
        self.assertLess(out.index("BASE"), out.index("review-plan"))


if __name__ == "__main__":
    unittest.main()
