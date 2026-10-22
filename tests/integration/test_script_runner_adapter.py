import json
import os
import shutil
import stat
import subprocess
import tempfile
import time
import unittest
from urllib.parse import quote

from lightcycle.adapters.run_groups import RunGroupsAdapter
from lightcycle.adapters.script_runner import ScriptRunnerAdapter
from lightcycle.config import Config


class ScriptRunnerTestCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.dir, ignore_errors=True))
        self.home = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.home, ignore_errors=True))
        self.config = Config(environ={"LC_HOME": self.home, "LC_WORKER_HISTORY": "20"})
        self.runner = ScriptRunnerAdapter(self.config, RunGroupsAdapter())

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

        result = self.runner.run(path, self.dir, self.env(), "", 30, "script-t")

        self.assertEqual((result.exit_code, result.stdout, result.stderr_tail), (0, "out\n", "err\n"))

    def test_environment_stdin_and_working_directory_arrive(self):
        path = self.script('echo "$LC_PROBE"\npwd -P\ncat\n')
        cwd = tempfile.mkdtemp(dir=self.dir)

        result = self.runner.run(path, cwd, self.env(LC_PROBE="hello"), '{"a": 1}', 30, "script-t")

        lines = result.stdout.splitlines()
        self.assertEqual(lines[0], "hello")
        self.assertEqual(os.path.realpath(lines[1]), os.path.realpath(cwd))
        self.assertEqual(json.loads(lines[2]), {"a": 1})

    def test_stdin_is_closed_after_the_object(self):
        path = self.script("cat > /dev/null\necho done\n")

        result = self.runner.run(path, self.dir, self.env(), "{}", 30, "script-t")

        self.assertEqual((result.exit_code, result.timed_out), (0, False))

    def test_a_non_zero_exit_is_reported_with_the_stderr_tail(self):
        path = self.script("echo bad >&2\nexit 3\n")

        result = self.runner.run(path, self.dir, self.env(), "", 30, "script-t")

        self.assertEqual((result.exit_code, result.stderr_tail, result.timed_out), (3, "bad\n", False))

    def test_a_timeout_kills_the_script_and_flags_it(self):
        path = self.script("echo partial\nexec sleep 30\n")
        started = time.monotonic()

        result = self.runner.run(path, self.dir, self.env(), "", 1, "script-t")

        self.assertTrue(result.timed_out)
        self.assertIsNone(result.exit_code)
        self.assertLess(time.monotonic() - started, 20)

    def test_a_timeout_kills_a_backgrounded_grandchild_too(self):
        pid_file = os.path.join(self.dir, "grandchild.pid")
        path = self.script("sleep 300 &\necho $! > %s\nwait\n" % pid_file)

        result = self.runner.run(path, self.dir, self.env(), "", 1, "script-t")

        self.assertTrue(result.timed_out)
        with open(pid_file) as f:
            pid = int(f.read().strip())
        deadline = time.monotonic() + 10
        alive = True
        while alive and time.monotonic() < deadline:
            try:
                os.kill(pid, 0)
                time.sleep(0.05)
            except ProcessLookupError:
                alive = False
        self.assertFalse(alive)

    def test_a_script_that_cannot_start_is_reported_not_raised(self):
        result = self.runner.run(os.path.join(self.dir, "missing.sh"), self.dir, self.env(), "", 5, "script-t")

        self.assertIsNone(result.exit_code)
        self.assertTrue(result.stderr_tail)

    def test_the_stderr_tail_is_bounded(self):
        path = self.script("i=0\nwhile [ $i -lt 3000 ]; do echo xxxxxxxxxx >&2; i=$((i+1)); done\n")

        result = self.runner.run(path, self.dir, self.env(), "", 30, "script-t")

        self.assertEqual(len(result.stderr_tail), 2000)


class TestBackground(ScriptRunnerTestCase):
    def test_start_returns_before_the_script_exits_and_poll_goes_none_then_result_then_forgets(self):
        gate = os.path.join(self.dir, "gate")
        path = self.script('while [ ! -e "%s" ]; do sleep 0.05; done\necho finished\n' % gate)

        self.runner.start("k", path, self.dir, self.env(), "", 30, "script-t")

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
        self.runner.start("k", path, self.dir, self.env(), "", 1, "script-t")

        with self.assertRaises(ValueError):
            self.runner.start("k", path, self.dir, self.env(), "", 1, "script-t")
        self.wait("k")


class TestRunLog(ScriptRunnerTestCase):
    def logs(self, prefix=""):
        directory = os.path.join(self.home, "logs")
        return sorted(n for n in os.listdir(directory) if n.startswith(prefix))

    def read(self, result):
        with open(result.log_path) as f:
            return f.read()

    def test_both_streams_land_in_sections_with_an_exit_footer(self):
        path = self.script("echo out\necho err >&2\n")

        result = self.runner.run(path, self.dir, self.env(), "", 30, "script-t")

        text = self.read(result)
        self.assertIn("script: %s" % path, text)
        self.assertIn("--- stderr ---\n", text)
        self.assertIn("--- stdout ---\n", text)
        self.assertIn("err\n", text)
        self.assertIn("out\n", text)
        self.assertIn("exit 0 (", text)
        self.assertTrue(os.path.basename(result.log_path).startswith("script-t-"))

    def test_the_log_holds_all_of_stderr_while_the_tail_is_bounded(self):
        path = self.script("i=0; while [ $i -lt 800 ]; do echo line-$i >&2; i=$((i+1)); done\nexit 3\n")

        result = self.runner.run(path, self.dir, self.env(), "", 30, "script-t")

        text = self.read(result)
        self.assertIn("line-0\n", text)
        self.assertIn("line-799\n", text)
        self.assertIn("exit 3 (", text)
        self.assertEqual(len(result.stderr_tail), 2000)

    def test_a_timeout_leaves_a_timed_out_footer_and_the_stdout_printed_before_the_kill(self):
        path = self.script("echo partial\nexec sleep 30\n")

        result = self.runner.run(path, self.dir, self.env(), "", 1, "script-t")

        text = self.read(result)
        self.assertIn("partial", text)
        self.assertIn("timed out after 1s", text)

    def test_a_script_that_cannot_start_leaves_a_could_not_start_footer(self):
        result = self.runner.run(
            os.path.join(self.dir, "missing.sh"), self.dir, self.env(), "", 5, "script-t")

        self.assertIn("could not start", self.read(result))
        self.assertTrue(result.stderr_tail)

    def test_stderr_is_in_the_log_while_the_script_is_still_running(self):
        gate = os.path.join(self.dir, "gate")
        path = self.script('echo first >&2\nwhile [ ! -e "%s" ]; do sleep 0.05; done\n' % gate)

        log_path = self.runner.start("k", path, self.dir, self.env(), "", 30, "script-t")

        deadline = time.monotonic() + 30
        seen = ""
        while time.monotonic() < deadline and "first" not in seen:
            time.sleep(0.05)
            with open(log_path) as f:
                seen = f.read()
        open(gate, "w").close()
        self.wait("k")
        self.assertIn("first", seen)

    def test_stdout_is_in_the_log_while_the_script_is_still_running_and_the_result_is_unchanged(self):
        gate = os.path.join(self.dir, "gate")
        path = self.script(
            'echo first-out\necho first-err >&2\nwhile [ ! -e "%s" ]; do sleep 0.05; done\n' % gate)

        log_path = self.runner.start("k", path, self.dir, self.env(), "", 30, "script-t")

        deadline = time.monotonic() + 30
        seen = ""
        while time.monotonic() < deadline and not ("first-out" in seen and "first-err" in seen):
            time.sleep(0.05)
            with open(log_path) as f:
                seen = f.read()
        open(gate, "w").close()
        result = self.wait("k")
        self.assertIn("first-out", seen)
        self.assertIn("first-err", seen)
        self.assertEqual(
            (result.exit_code, result.stdout, result.stderr_tail), (0, "first-out\n", "first-err\n"))

    def test_only_the_newest_logs_of_a_kind_survive_and_other_files_are_untouched(self):
        config = Config(environ={"LC_HOME": self.home, "LC_WORKER_HISTORY": "2"})
        runner = ScriptRunnerAdapter(config, RunGroupsAdapter())
        logs = os.path.join(self.home, "logs")
        os.makedirs(logs, exist_ok=True)
        for name in ("worker-agent-x.log", "guard-g-1.log"):
            open(os.path.join(logs, name), "w").close()
        path = self.script("true\n")

        for _ in range(3):
            runner.run(path, self.dir, self.env(), "", 30, "script-t")
            time.sleep(0.01)

        self.assertEqual(len(self.logs("script-")), 2)
        self.assertEqual(self.logs("worker-"), ["worker-agent-x.log"])
        self.assertEqual(self.logs("guard-"), ["guard-g-1.log"])


class TestPrunedScriptLog(ScriptRunnerTestCase):
    def test_a_done_script_step_whose_log_was_pruned_resolves_to_no_log(self):
        from lightcycle.adapters.fsio import FsAdapter
        from lightcycle.application.pool.resolve_log import ResolveLogInput, ResolveLogUseCase
        from tests.support.fake_store import FakeStore
        from tests.support.fake_workers import FakeWorkers
        from tests.support.step_factory import create_owned_step

        config = Config(environ={"LC_HOME": self.home, "LC_WORKER_HISTORY": "2"})
        runner = ScriptRunnerAdapter(config, RunGroupsAdapter())
        path = self.script("true\n")
        store = FakeStore()
        steps = []
        for index in range(3):
            step = create_owned_step(store, "s%d" % index, stage="script", role="engine")
            log_path = runner.run(path, self.dir, self.env(), "", 30, "script-t").log_path
            store.set_log(step, log_path)
            store.complete_node(step, "done")
            steps.append(step)
            time.sleep(0.01)
        resolve = ResolveLogUseCase(store, FakeWorkers(), FsAdapter(config), config)

        resolved = [resolve.execute(ResolveLogInput(target=step)).path for step in steps]

        self.assertIsNone(resolved[0])
        self.assertTrue(all(resolved[1:]))


class TestOrphanedRecords(ScriptRunnerTestCase):
    def _record(self, key, pid, started):
        directory = os.path.join(self.home, "script-runs")
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, quote(key, safe="") + ".json")
        with open(path, "w") as f:
            json.dump({"pid": pid, "started": started}, f)
        return path

    def test_an_absent_directory_reads_as_no_orphans(self):
        self.assertEqual(self.runner.orphaned(), [])

    def test_a_record_left_for_a_live_child_is_reported_by_a_second_instance_then_removed_when_dead(self):
        path = self.script("exec sleep 300\n")
        runner = ScriptRunnerAdapter(self.config, RunGroupsAdapter())
        runner.start("step:S-1", path, self.dir, self.env(), "", 300, "script-t")
        record = os.path.join(self.home, "script-runs", "step%3AS-1.json")
        deadline = time.monotonic() + 10
        while not os.path.exists(record) and time.monotonic() < deadline:
            time.sleep(0.05)
        with open(record) as f:
            pid = json.load(f)["pid"]
        second = ScriptRunnerAdapter(self.config, RunGroupsAdapter())

        self.assertEqual(second.orphaned(), ["step:S-1"])
        self.assertTrue(os.path.exists(record))
        self.assertEqual(runner.orphaned(), [])

        os.killpg(pid, 9)
        deadline = time.monotonic() + 10
        while second.orphaned() and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertEqual(second.orphaned(), [])
        self.assertFalse(os.path.exists(record))

    def test_a_record_with_a_different_start_time_is_treated_as_dead(self):
        child = subprocess.Popen(["sleep", "300"])
        self.addCleanup(child.wait)
        self.addCleanup(child.kill)
        record = self._record("step:S-2", child.pid, "Mon Jan  1 00:00:00 2001")

        self.assertEqual(self.runner.orphaned(), [])
        self.assertFalse(os.path.exists(record))


class TestRunGroupsStop(ScriptRunnerTestCase):
    def _spawn(self, groups, label, body):
        proc = subprocess.Popen(
            [self.script(body, name=label + ".sh")], cwd=self.dir, env=self.env(),
            start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        groups.register(label, proc)
        self.addCleanup(proc.wait)
        return proc

    def test_nothing_registered_stops_nothing(self):
        stopped = RunGroupsAdapter().stop(1)
        self.assertEqual((stopped.terminated, stopped.killed), ([], []))

    def test_a_sigterm_script_is_terminated_and_one_that_ignores_it_is_killed_after_the_grace(self):
        groups = RunGroupsAdapter()
        pid_file = os.path.join(self.dir, "stubborn-child.pid")
        polite = self._spawn(groups, "polite", "exec sleep 300\n")
        stubborn = self._spawn(
            groups, "stubborn",
            "trap '' TERM\n(trap '' TERM; exec sleep 300) &\necho $! > %s\nwhile true; do sleep 1; done\n"
            % pid_file)
        deadline = time.monotonic() + 10
        while not os.path.exists(pid_file) and time.monotonic() < deadline:
            time.sleep(0.05)
        time.sleep(0.2)

        stopped = groups.stop(1)

        self.assertEqual(stopped.terminated, ["polite", "stubborn"])
        self.assertEqual(stopped.killed, ["stubborn"])
        polite.wait(10)
        stubborn.wait(10)
        with open(pid_file) as f:
            grandchild = int(f.read().strip())
        deadline = time.monotonic() + 10
        alive = True
        while alive and time.monotonic() < deadline:
            try:
                os.kill(grandchild, 0)
                time.sleep(0.05)
            except ProcessLookupError:
                alive = False
        self.assertFalse(alive)
