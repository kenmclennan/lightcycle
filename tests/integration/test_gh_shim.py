import datetime
import os
import re
import shutil
import stat
import subprocess
import tempfile
import unittest

from lightcycle.adapters.gh_shim import ensure_gh_shim
from lightcycle.adapters.spawner import spawn_worker
from lightcycle.config import Config

SYSTEM_PATH = "/usr/bin:/bin"
FAKE_GH = """#!/bin/sh
body=$(cat)
printf '%s|%s\\n' "$*" "$body" >> "$GH_REC"
case "$1" in
  fail) echo "out-from-fake"; exit 7;;
esac
exit 0
"""
LINE = re.compile(r"^(\d+)\t([^\t]+)\t(\d+)\t(.*)$")


class _Env(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.fake_dir = os.path.join(self.root, "fake-bin")
        os.makedirs(self.fake_dir)
        fake = os.path.join(self.fake_dir, "gh")
        with open(fake, "w") as f:
            f.write(FAKE_GH)
        os.chmod(fake, 0o755)
        self.rec = os.path.join(self.root, "gh-rec")
        self.home = os.path.join(self.root, "home")
        os.makedirs(self.home)
        self.shim_dir = ensure_gh_shim(self.home)
        self.logs = os.path.join(self.home, "logs")

    def recorded(self):
        with open(self.rec) as f:
            return f.read().splitlines()

    def log_lines(self, name):
        with open(os.path.join(self.logs, name)) as f:
            return f.read().splitlines()


class TestGhShimDirect(_Env):
    def _run(self, args, spawnid="abc12345", input_text="", logs_mode=None):
        env = {
            "PATH": os.pathsep.join([self.shim_dir, self.fake_dir, SYSTEM_PATH]),
            "GH_REC": self.rec,
        }
        if spawnid:
            env["LC_SPAWNID"] = spawnid
        return subprocess.run(
            [os.path.join(self.shim_dir, "gh")] + args, input=input_text, text=True,
            capture_output=True, env=env, timeout=30)

    def test_the_real_gh_gets_the_same_argv_and_stdin_and_the_exit_code_passes_through(self):
        ok = self._run(["api", "-X", "PUT", "repos/o/r"], input_text="payload")
        failed = self._run(["fail", "x"])

        self.assertEqual((ok.returncode, failed.returncode), (0, 7))
        self.assertEqual(failed.stdout, "out-from-fake\n")
        self.assertEqual(self.recorded(), ["api -X PUT repos/o/r|payload", "fail x|"])

    def test_each_call_appends_one_line_to_the_spawns_file_in_the_documented_format(self):
        self._run(["api", "-X", "PUT", "repos/o/r", "-f", "x=y"])
        self._run(["fail", "line1\nline2"])
        self._run(["pr"])

        lines = self.log_lines("gh-calls-abc12345.log")

        self.assertEqual(len(lines), 3)
        parsed = [LINE.match(l) for l in lines]
        self.assertTrue(all(parsed), lines)
        self.assertEqual([m.group(2) for m in parsed], ["abc12345"] * 3)
        self.assertEqual([m.group(3) for m in parsed], ["0", "7", "0"])
        self.assertEqual(parsed[0].group(4), "api -X PUT repos/o/r")
        self.assertEqual(parsed[1].group(4), "fail line1 line2")

    def test_a_call_with_no_spawn_id_lands_in_the_pool_file_for_today_with_source_pool(self):
        self._run(["api", "user"], spawnid=None)

        today = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d")
        lines = self.log_lines("gh-calls-pool-%s.log" % today)

        self.assertEqual(len(lines), 1)
        self.assertEqual(LINE.match(lines[0]).group(2), "pool")

    @unittest.skipIf(os.geteuid() == 0, "root ignores directory permissions")
    def test_a_failing_log_append_changes_neither_output_nor_exit_code(self):
        os.chmod(self.logs, stat.S_IRUSR | stat.S_IXUSR)
        self.addCleanup(os.chmod, self.logs, stat.S_IRWXU)

        failed = self._run(["fail", "x"])

        self.assertEqual(failed.returncode, 7)
        self.assertEqual(failed.stdout, "out-from-fake\n")
        self.assertEqual(failed.stderr, "")

    def test_ensure_gh_shim_is_idempotent_and_executable(self):
        before = os.stat(os.path.join(self.shim_dir, "gh")).st_mtime_ns

        again = ensure_gh_shim(self.home)

        self.assertEqual(again, self.shim_dir)
        self.assertEqual(os.stat(os.path.join(again, "gh")).st_mtime_ns, before)
        self.assertTrue(os.access(os.path.join(again, "gh"), os.X_OK))


class TestGhShimThroughSpawnWorker(_Env):
    def test_a_fake_worker_command_calling_gh_three_times_leaves_one_line_per_call(self):
        command = (
            "gh api repos/o/r </dev/null; "
            "echo body | gh api -X PUT repos/o/r/pulls/1/update-branch; "
            "gh fail x </dev/null; exit 0"
        )
        config = Config(environ={
            "LC_HOME": self.home, "LC_MAX_AGENTS": "1", "LC_SPAWN_CMD": command,
            "PATH": os.pathsep.join([self.fake_dir, SYSTEM_PATH]), "GH_REC": self.rec,
        })

        spawned = spawn_worker(config, "agent")
        os.waitpid(spawned["pid"], 0)

        lines = self.log_lines("gh-calls-%s.log" % spawned["spawnid"])
        self.assertEqual(len(lines), 3)
        parsed = [LINE.match(l) for l in lines]
        self.assertEqual({m.group(2) for m in parsed}, {spawned["spawnid"]})
        self.assertEqual([m.group(3) for m in parsed], ["0", "0", "7"])
        self.assertEqual(
            self.recorded(),
            ["api repos/o/r|", "api -X PUT repos/o/r/pulls/1/update-branch|body", "fail x|"])


if __name__ == "__main__":
    unittest.main()
