import json
import os
import shutil
import stat
import tempfile
import time
import unittest

from lightcycle.adapters.script_runner import ScriptRunnerAdapter


class ScriptRunnerTestCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.dir, ignore_errors=True))
        self.runner = ScriptRunnerAdapter()

    def script(self, body, name="s.sh"):
        path = os.path.join(self.dir, name)
        with open(path, "w") as f:
            f.write("#!/bin/sh\n" + body)
        os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)
        return path

    def env(self, **extra):
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin")}
        env.update(extra)
        return env

    def wait(self, key, limit=30.0):
        deadline = time.monotonic() + limit
        while time.monotonic() < deadline:
            result = self.runner.poll(key)
            if result is not None:
                return result
            time.sleep(0.02)
        self.fail("script %s never finished" % key)


class TestRun(ScriptRunnerTestCase):
    def test_stdout_and_stderr_are_captured_apart(self):
        path = self.script("echo out\necho err >&2\n")

        result = self.runner.run(path, self.dir, self.env(), "", 30)

        self.assertEqual((result.exit_code, result.stdout, result.stderr_tail), (0, "out\n", "err\n"))

    def test_environment_stdin_and_working_directory_arrive(self):
        path = self.script('echo "$LC_PROBE"\npwd -P\ncat\n')
        cwd = tempfile.mkdtemp(dir=self.dir)

        result = self.runner.run(path, cwd, self.env(LC_PROBE="hello"), '{"a": 1}', 30)

        lines = result.stdout.splitlines()
        self.assertEqual(lines[0], "hello")
        self.assertEqual(os.path.realpath(lines[1]), os.path.realpath(cwd))
        self.assertEqual(json.loads(lines[2]), {"a": 1})

    def test_stdin_is_closed_after_the_object(self):
        path = self.script("cat > /dev/null\necho done\n")

        result = self.runner.run(path, self.dir, self.env(), "{}", 30)

        self.assertEqual((result.exit_code, result.timed_out), (0, False))

    def test_a_non_zero_exit_is_reported_with_the_stderr_tail(self):
        path = self.script("echo bad >&2\nexit 3\n")

        result = self.runner.run(path, self.dir, self.env(), "", 30)

        self.assertEqual((result.exit_code, result.stderr_tail, result.timed_out), (3, "bad\n", False))

    def test_a_timeout_kills_the_script_and_flags_it(self):
        path = self.script("echo partial\nexec sleep 30\n")
        started = time.monotonic()

        result = self.runner.run(path, self.dir, self.env(), "", 1)

        self.assertTrue(result.timed_out)
        self.assertIsNone(result.exit_code)
        self.assertLess(time.monotonic() - started, 20)

    def test_a_script_that_cannot_start_is_reported_not_raised(self):
        result = self.runner.run(os.path.join(self.dir, "missing.sh"), self.dir, self.env(), "", 5)

        self.assertIsNone(result.exit_code)
        self.assertTrue(result.stderr_tail)

    def test_the_stderr_tail_is_bounded(self):
        path = self.script("i=0\nwhile [ $i -lt 3000 ]; do echo xxxxxxxxxx >&2; i=$((i+1)); done\n")

        result = self.runner.run(path, self.dir, self.env(), "", 30)

        self.assertEqual(len(result.stderr_tail), 2000)


class TestBackground(ScriptRunnerTestCase):
    def test_start_returns_before_the_script_exits_and_poll_goes_none_then_result_then_forgets(self):
        gate = os.path.join(self.dir, "gate")
        path = self.script('while [ ! -e "%s" ]; do sleep 0.05; done\necho finished\n' % gate)

        self.runner.start("k", path, self.dir, self.env(), "", 30)

        self.assertEqual(self.runner.running(), ["k"])
        self.assertIsNone(self.runner.poll("k"))
        open(gate, "w").close()
        result = self.wait("k")
        self.assertEqual(result.stdout, "finished\n")
        self.assertEqual(self.runner.running(), [])
        with self.assertRaises(KeyError):
            self.runner.poll("k")

    def test_starting_a_running_key_is_an_error(self):
        path = self.script("sleep 5\n")
        self.runner.start("k", path, self.dir, self.env(), "", 1)

        with self.assertRaises(ValueError):
            self.runner.start("k", path, self.dir, self.env(), "", 1)
        self.wait("k")
