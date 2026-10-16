import contextlib
import datetime
import io
import os
import stat
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

import lightcycle.cli as cli
from lightcycle.adapters.lifecycle_runner import LifecycleRunnerAdapter
from lightcycle.adapters.workflow_bundle import WorkflowBundleAdapter
from lightcycle.adapters.workflow_source import WorkflowSourceAdapter
from lightcycle.application.pool.lifecycle_cadence import LifecycleCadenceUseCase
from lightcycle.application.workflows.add import AddWorkflowSourceUseCase
from lightcycle.application.workflows.upgrade import UpgradeWorkflowSourceUseCase
from lightcycle.config import _SEED_KEYS, Config
from lightcycle.container import Container
from lightcycle.ports.workflow_source import FetchedBundle
from tests.integration.test_workflow_simulate import _STEPS, _WORKFLOW_TEXT, SimulateTestCase


def _config(home, extra=""):
    path = os.path.join(home, "config")
    overrides = {"projects": os.path.join(home, "projects"), "trusted-authors": "me"}
    lines = "".join("%s: %s\n" % (k, overrides.get(k, v)) for k, v in _SEED_KEYS)
    Path(path).write_text(lines + extra)
    return Config(environ={"LC_HOME": home, "LC_CONFIG": path})


def _script(directory, name, text):
    path = os.path.join(directory, name)
    Path(path).write_text("#!/bin/sh\n" + text)
    os.chmod(path, 0o755)
    return path


class TestRunnerAdapter(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.runner = LifecycleRunnerAdapter(_config(self.home))
        self.work = tempfile.mkdtemp()

    def test_run_reports_exit_code_output_cwd_and_environment(self):
        script = _script(self.work, "s.sh", 'echo "in $(pwd) with $GREETING"; echo oops >&2; exit 3\n')
        result = self.runner.run(
            script, self.work, {"GREETING": "hi", "PATH": os.environ["PATH"]}, 10, "hook-t")
        self.assertEqual(result.exit_code, 3)
        self.assertFalse(result.ok)
        self.assertIn("with hi", result.output)
        self.assertIn(os.path.realpath(self.work), os.path.realpath(result.output.split("in ")[1].split()[0]))
        self.assertIn("oops", result.output)

    def test_run_leaves_a_hook_log_and_returns_its_path(self):
        script = _script(self.work, "s.sh", "echo hi\n")
        result = self.runner.run(script, self.work, {"PATH": os.environ["PATH"]}, 10, "hook-acme-build-maintain")
        self.assertTrue(os.path.basename(result.log_path).startswith("hook-acme-build-maintain-"))
        self.assertIn("hi", Path(result.log_path).read_text())

    def test_run_keeps_only_the_output_tail(self):
        script = _script(self.work, "s.sh", 'i=0; while [ $i -lt 3000 ]; do echo line-$i; i=$((i+1)); done\n')
        result = self.runner.run(script, self.work, {"PATH": os.environ["PATH"]}, 10, "hook-t")
        self.assertLessEqual(len(result.output), 2000)
        self.assertIn("line-2999", result.output)

    def test_a_timeout_kills_the_process_and_says_so(self):
        script = _script(self.work, "s.sh", "exec sleep 30\n")
        started = time.monotonic()
        result = self.runner.run(script, self.work, {"PATH": os.environ["PATH"]}, 1, "hook-t")
        self.assertTrue(result.timed_out)
        self.assertFalse(result.ok)
        self.assertLess(time.monotonic() - started, 10)

    def test_a_script_that_cannot_start_is_a_failure_not_an_exception(self):
        result = self.runner.run(os.path.join(self.work, "missing.sh"), self.work, {}, 5, "hook-t")
        self.assertFalse(result.ok)
        self.assertIsNone(result.exit_code)

    def _wait(self, key):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            result = self.runner.poll(key)
            if result is not None:
                return result
            time.sleep(0.02)
        self.fail("process %s never finished" % key)

    def test_start_returns_before_the_script_exits_and_poll_reports_the_outcome(self):
        gate = os.path.join(self.work, "go")
        script = _script(self.work, "s.sh", 'while [ ! -e "%s" ]; do sleep 0.02; done; exit 5\n' % gate)
        self.runner.start("acme/build", script, self.work, {"PATH": os.environ["PATH"]}, 10, "hook-t")
        self.assertEqual(self.runner.running(), ["acme/build"])
        self.assertIsNone(self.runner.poll("acme/build"))
        Path(gate).write_text("x")
        result = self._wait("acme/build")
        self.assertEqual(result.exit_code, 5)
        self.assertEqual(self.runner.running(), [])

    def test_a_background_script_outliving_its_timeout_reports_a_timeout(self):
        script = _script(self.work, "s.sh", "exec sleep 30\n")
        self.runner.start("acme/build", script, self.work, {"PATH": os.environ["PATH"]}, 1, "hook-t")
        self.assertTrue(self._wait("acme/build").timed_out)

    def test_start_on_a_running_key_and_poll_on_an_unknown_key_are_errors(self):
        script = _script(self.work, "s.sh", "exec sleep 30\n")
        self.runner.start("k", script, self.work, {"PATH": os.environ["PATH"]}, 1, "hook-t")
        with self.assertRaises(ValueError):
            self.runner.start("k", script, self.work, {}, 1, "hook-t")
        with self.assertRaises(KeyError):
            self.runner.poll("unknown")
        self._wait("k")

    def test_due_times_round_trip_through_a_file_a_second_adapter_reads(self):
        due = datetime.datetime(2026, 1, 2, 3, 0)
        self.assertIsNone(self.runner.last_due("acme/build"))
        self.runner.record_due("acme/build", due)
        self.runner.record_due("acme/ship", due)
        second = LifecycleRunnerAdapter(_config(self.home))
        self.assertEqual(second.last_due("acme/build"), due)
        self.assertTrue(os.path.exists(os.path.join(self.home, "lifecycle-state.json")))

    def test_an_unreadable_state_file_raises_rather_than_reading_as_empty(self):
        Path(self.home, "lifecycle-state.json").write_text("{not json")
        with self.assertRaises(ValueError):
            self.runner.last_due("acme/build")

    def test_remove_data_dir_refuses_a_path_outside_the_data_root(self):
        outside = tempfile.mkdtemp()
        with self.assertRaises(ValueError):
            self.runner.remove_data_dir(outside)
        self.assertTrue(os.path.isdir(outside))
        inside = os.path.join(self.home, "workflow-data", "acme", "build")
        self.runner.ensure_data_dir(inside)
        self.assertEqual(self.runner.list_data_dirs(os.path.dirname(inside)), ["build"])
        self.runner.remove_data_dir(inside)
        self.assertFalse(self.runner.data_dir_exists(inside))

    def test_remove_empty_dir_removes_only_an_empty_directory_under_the_data_root(self):
        origin = os.path.join(self.home, "workflow-data", "acme")
        self.runner.ensure_data_dir(os.path.join(origin, "build"))
        self.runner.remove_empty_dir(origin)
        self.assertTrue(os.path.isdir(origin))
        self.runner.remove_data_dir(os.path.join(origin, "build"))
        self.runner.remove_empty_dir(origin)
        self.assertFalse(os.path.exists(origin))
        outside = tempfile.mkdtemp()
        with self.assertRaises(ValueError):
            self.runner.remove_empty_dir(outside)
        self.assertTrue(os.path.isdir(outside))


class TestPinCarriesScripts(unittest.TestCase):
    def test_pin_writes_scripts_with_the_executable_bit_and_a_bundle_without_pins_as_before(self):
        home = tempfile.mkdtemp()
        adapter = WorkflowSourceAdapter(_config(home), WorkflowBundleAdapter())
        bundle = FetchedBundle(
            manifest='name = "acme"\ncontract = 1\n', sha="s1", steps={}, workflows={},
            scripts={"install.sh": (b"#!/bin/sh\n", True), "lib/helper.py": (b"x = 1\n", False)})
        target = adapter.pin("acme", bundle)
        install = os.path.join(target, "scripts", "install.sh")
        helper = os.path.join(target, "scripts", "lib", "helper.py")
        self.assertTrue(os.stat(install).st_mode & stat.S_IXUSR)
        self.assertFalse(os.stat(helper).st_mode & stat.S_IXUSR)
        self.assertEqual(Path(helper).read_text(), "x = 1\n")
        plain = adapter.pin("acme", FetchedBundle(
            manifest='name = "acme"\ncontract = 1\n', sha="s2", steps={}, workflows={}))
        self.assertFalse(os.path.exists(os.path.join(plain, "scripts")))

    def test_fetch_reads_the_scripts_tree_and_skips_symlinks(self):
        repo = tempfile.mkdtemp()
        _git(repo, "init", "-q", "-b", "main")
        _git(repo, "config", "user.email", "t@t")
        _git(repo, "config", "user.name", "t")
        Path(repo, "source.toml").write_text('name = "acme"\ncontract = 1\n')
        os.makedirs(os.path.join(repo, "scripts", "sub"))
        _script(os.path.join(repo, "scripts"), "run.sh", "exit 0\n")
        Path(repo, "scripts", "sub", "data.txt").write_text("d")
        os.symlink("/etc/hosts", os.path.join(repo, "scripts", "link"))
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "seed")
        adapter = WorkflowSourceAdapter(_config(tempfile.mkdtemp()), WorkflowBundleAdapter())
        bundle = adapter.fetch(repo, "main")
        self.assertEqual(sorted(bundle.scripts), ["run.sh", "sub/data.txt"])
        self.assertTrue(bundle.scripts["run.sh"][1])
        self.assertFalse(bundle.scripts["sub/data.txt"][1])


def _git(root, *args):
    subprocess.run(["git", "-C", root, *args], check=True, capture_output=True, text=True)


_LIFECYCLE_FRONT = (
    "---\nlifecycle:\n  install: scripts/install.sh\n  upgrade: scripts/upgrade.sh\n"
    "  maintain: scripts/maintain.sh\n  cron: 0 3 * * *\nconfig:\n  api-token: required\n"
    "  out: optional\nconfig-example:\n  api-token: example\n  out: {out}\n---\n")

_RECORD = (
    'echo "$LC_WORKFLOW_HOOK $LC_WORKFLOW_NAME $LC_WORKFLOW_SHA '
    '${LC_WORKFLOW_FROM_SHA:-} ${LC_WORKFLOW_TO_SHA:-} $LC_WORKFLOW_CONFIG_API_TOKEN" '
    '>> "$LC_WORKFLOW_DATA_DIR/log"\n')


def _lifecycle_repo(out):
    repo = tempfile.mkdtemp()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    Path(repo, "source.toml").write_text(
        'name = "acme"\ncontract = 1\nrequires-engine = ">=0.1.0"\n')
    os.makedirs(os.path.join(repo, "workflows"))
    os.makedirs(os.path.join(repo, "steps"))
    os.makedirs(os.path.join(repo, "scripts"))
    Path(repo, "workflows", "build.md").write_text(
        _LIFECYCLE_FRONT.format(out=out) + "entry: code\n")
    Path(repo, "steps", "code.md").write_text("---\nmodel: x\n---\nbody\n")
    for name in ("install.sh", "upgrade.sh", "maintain.sh"):
        _script(os.path.join(repo, "scripts"), name, _RECORD)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "seed")
    return repo


def _head(repo):
    return subprocess.run(
        ["git", "-C", repo, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()


class TestEndToEndOnAScratchHome(unittest.TestCase):
    def test_add_upgrade_and_one_due_tick_run_the_three_hooks_in_order(self):
        home = tempfile.mkdtemp()
        config = _config(home, "workflow-acme-build:\n  api-token: tok\n")
        container = Container(config=config)
        repo = _lifecycle_repo(out="/unused")
        first = _head(repo)

        AddWorkflowSourceUseCase(
            container.workflow_source, container.store, config, container.fs,
            container.workflow_lifecycle()).execute(url=repo, ref="main", name=None)
        data_dir = config.workflow_data_dir("acme", "build")
        self.assertTrue(os.path.isdir(data_dir))

        Path(repo, "marker").write_text("v2")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "second")
        second = _head(repo)
        UpgradeWorkflowSourceUseCase(
            container.workflow_source, container.store, config, container.fs,
            container.workflow_lifecycle()).execute("acme")

        container.lifecycle_runner.record_due("acme/build", datetime.datetime(2026, 1, 1, 3, 0))
        gate = LifecycleCadenceUseCase(
            container.store, config, container.workflow_source, container.workflow_lifecycle(),
            container.lifecycle_runner, config.audit_shortcode)
        due = datetime.datetime(2026, 1, 2, 3, 0, 0).timestamp()
        started = gate.execute(due)
        self.assertEqual(started.started, ["acme/build"])
        reaped = None
        for step in range(200):
            reaped = gate.execute(due + 60)
            if reaped.reaped:
                break
            time.sleep(0.05)
        self.assertEqual(reaped.reaped, ["acme/build"])
        self.assertEqual(reaped.filed, [])

        lines = Path(data_dir, "log").read_text().splitlines()
        self.assertEqual(lines, [
            "install build %s   tok" % first,
            "upgrade build %s %s %s tok" % (second, first, second),
            "maintain build %s   tok" % second,
        ])

    def test_check_passes_on_the_pinned_bundle(self):
        home = tempfile.mkdtemp()
        config = _config(home, "workflow-acme-build:\n  api-token: tok\n")
        container = Container(config=config)
        repo = _lifecycle_repo(out="/unused")
        AddWorkflowSourceUseCase(
            container.workflow_source, container.store, config, container.fs,
            container.workflow_lifecycle()).execute(url=repo, ref="main", name=None)
        original = cli._container
        self.addCleanup(lambda: cli.set_container(original))
        cli.set_container(container)
        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            rc = cli._workflow_check_pinned("acme/build", False)
        self.assertEqual(rc, 0, err.getvalue())
        self.assertNotIn("lifecycle", err.getvalue())


class TestSimulateRunsTheLifecycle(SimulateTestCase):
    def test_simulate_runs_install_upgrade_maintain_with_the_example_config(self):
        out = os.path.join(tempfile.mkdtemp(), "record")
        selector = self._install(_LIFECYCLE_FRONT.format(out=out) + _WORKFLOW_TEXT, _STEPS)
        bundle = Path(cli._container.config.data_root(), "workflows", "acme", "sha1")
        os.makedirs(bundle / "scripts")
        for name in ("install.sh", "upgrade.sh", "maintain.sh"):
            _script(str(bundle / "scripts"), name, 'echo "$LC_WORKFLOW_HOOK $LC_WORKFLOW_CONFIG_API_TOKEN" >> "$LC_WORKFLOW_CONFIG_OUT"\n')
        rc = cli._workflow_simulate(selector)
        self.assertEqual(rc, 0)
        self.assertEqual(
            Path(out).read_text().splitlines(),
            ["install example", "upgrade example", "maintain example"])

    def test_a_failing_hook_fails_the_simulation(self):
        selector = self._install(_LIFECYCLE_FRONT.format(out="/unused") + _WORKFLOW_TEXT, _STEPS)
        bundle = Path(cli._container.config.data_root(), "workflows", "acme", "sha1")
        os.makedirs(bundle / "scripts")
        _script(str(bundle / "scripts"), "install.sh", "exit 0\n")
        _script(str(bundle / "scripts"), "upgrade.sh", "echo broken; exit 9\n")
        _script(str(bundle / "scripts"), "maintain.sh", "exit 0\n")
        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            rc = cli._workflow_simulate(selector)
        self.assertNotEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
