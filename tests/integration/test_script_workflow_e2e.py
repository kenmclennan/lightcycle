import contextlib
import io
import os
import tempfile
import time
import unittest
from pathlib import Path

import lightcycle.cli as cli
from lightcycle.application.flow.complete_step import CompleteStepUseCase
from lightcycle.application.flow.park_step import ParkStepUseCase
from lightcycle.application.pool.schedule_cadence import ScheduleCadenceUseCase
from lightcycle.application.pool.script_stages import ScriptStageUseCase
from lightcycle.application.workflows.add import AddWorkflowSourceUseCase
from lightcycle.container import Container
from lightcycle.domain.work import State
from tests.integration.test_workflow_lifecycle import _config, _git
from tests.support.fake_script_runner import FakeScriptRunner
from tests.support.schedule_fakes import RecordingActivate
from tests.support.script_bundle import write_script_bundle

POLL_SH = """#!/bin/sh
cat > "$LC_WORKFLOW_DATA_DIR/stdin.json"
env | grep '^LC_' | sort > "$LC_WORKFLOW_DATA_DIR/env.txt"
mode=$(cat "$LC_WORKFLOW_DATA_DIR/mode" 2>/dev/null || echo found)
case "$mode" in
  found) echo '{"outcome": "found", "artifacts": {"digest": "3 new rows"}, "note": "rows found"}' ;;
  none) echo '{"outcome": "none"}' ;;
  crash) echo "boom: bad token" >&2; exit 4 ;;
  garbage) echo "not json" ;;
  undeclared) echo '{"outcome": "zzz"}' ;;
  slow) exec sleep 30 ;;
esac
"""

CHANGED_SH = """#!/bin/sh
cat > /dev/null
mode=$(cat "$LC_WORKFLOW_DATA_DIR/guard-mode" 2>/dev/null || echo pass)
case "$mode" in
  pass) echo '{"outcome": "pass", "title": "Sheet changed", "description": "d", "state": "c1"}' ;;
  fail) echo '{"outcome": "fail"}' ;;
  crash) echo "guard boom" >&2; exit 1 ;;
esac
"""

SCHEDULE_BLOCK = (
    "schedule-weekly:\n  enabled: true\n  workflow: acme/build\n  project: acme/app\n"
    "  cron: 0 * * * *\n  guard: script:scripts/changed.sh\n"
    "workflow-acme-build:\n  api-token: tok\n")


def script_repo(**kwargs):
    repo = tempfile.mkdtemp()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    options = {"poll_sh": POLL_SH, "changed_sh": CHANGED_SH, "config_block": True}
    options.update(kwargs)
    write_script_bundle(repo, **options)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "seed")
    return repo


class ScratchHome(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.config = _config(self.home, SCHEDULE_BLOCK)
        self.container = Container(config=self.config)
        self._orig = cli._container
        self.addCleanup(lambda: cli.set_container(self._orig))
        cli.set_container(self.container)

    def add(self, **kwargs):
        AddWorkflowSourceUseCase(
            self.container.workflow_source, self.container.store, self.config,
            self.container.fs, self.container.workflow_lifecycle()).execute(
                url=script_repo(**kwargs), ref="main", name=None)
        self.sha = self.container.workflow_source.current_sha("acme")
        self.pin = "acme/build@%s" % self.sha

    def data_dir(self):
        path = self.config.workflow_data_dir("acme", "build")
        os.makedirs(path, exist_ok=True)
        return path

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = cli.cmd_workflow(list(argv))
        return rc, out.getvalue(), err.getvalue()


class TestCheckAndSimulate(ScratchHome):
    def test_check_is_clean_and_simulate_reaches_every_outcome_without_a_process(self):
        fake = FakeScriptRunner()
        self.container.script_runner = fake
        self.add()

        check_rc, _, check_err = self.run_cli("check", "acme/build")
        sim_rc, sim_out, sim_err = self.run_cli("simulate", "acme/build", "--trace")

        self.assertEqual((check_rc, check_err), (0, ""))
        self.assertEqual((sim_rc, sim_err), (0, ""))
        self.assertIn("poll[found]", sim_out)
        self.assertIn("poll[none]", sim_out)
        self.assertIn("script guard scripts/changed.sh: pass ok", sim_out)
        self.assertIn("script guard scripts/changed.sh: fail ok", sim_out)
        self.assertEqual(fake.calls, [])

    def test_simulate_names_the_stage_and_outcome_a_fixture_lacks(self):
        partial = {"found": {"outcome": "found"}}
        self.add(stage_fixture=partial)

        rc, _, err = self.run_cli("simulate", "acme/build")

        self.assertEqual(rc, 1)
        self.assertIn("script stage 'poll'", err)
        self.assertIn("outcome none", err)

    def test_simulate_flags_a_guard_fixture_entry_that_does_not_parse(self):
        bad = {"pass": {"outcome": "pass"}, "fail": {"outcome": "fail"}}
        self.add(guard_fixture=bad)

        rc, _, err = self.run_cli("simulate", "acme/build")

        self.assertEqual(rc, 1)
        self.assertIn("script guard scripts/changed.sh", err)


class TestRealStage(ScratchHome):
    def setUp(self):
        super().setUp()
        self.add()
        c = self.container
        self.flow = c.flow_service()
        self.complete = CompleteStepUseCase(c.store, self.flow, None, self.config)
        self.gate = ScriptStageUseCase(
            c.store, self.flow, self.config, c.workflow_source, c.workflow_lifecycle(),
            c.script_runner, ParkStepUseCase(c.store), self.complete, None)

    def new_step(self):
        store = self.container.store
        item = store.create_item("t", "d", workflow=self.pin, shortcode="APP")
        store.add_artifact(item, "repo", "app")
        store.add_artifact(item, "brief", "look at the sheet")
        return store.create_step(step="poll", role="engine", parent=item)

    def drive(self, step, until):
        for n in range(400):
            self.flow.clear_cache()
            self.gate.execute(float(n))
            if until(self.container.store.get_node(step)):
                return self.container.store.get_node(step)
            time.sleep(0.05)
        self.fail("step %s never settled" % step)

    def set_mode(self, mode):
        Path(self.data_dir(), "mode").write_text(mode)

    def test_the_found_outcome_completes_the_step_with_its_artifact_and_note(self):
        self.set_mode("found")
        step = self.new_step()

        node = self.drive(step, lambda n: n.state == State.DONE)

        self.assertEqual(node.outcome, "found")
        artifacts = {a.type: a.value for a in self.container.store.item_artifacts(step)}
        self.assertEqual(artifacts["digest"], "3 new rows")
        item_steps = self.container.store.children(node.item)
        self.assertIn("finish", [s.stage for s in item_steps])

    def test_the_script_sees_its_environment_and_stdin(self):
        self.set_mode("none")
        step = self.new_step()
        node = self.drive(step, lambda n: n.state == State.DONE)

        self.assertEqual(node.outcome, "none")
        env = Path(self.data_dir(), "env.txt").read_text()
        for expected in (
                "LC_WORKFLOW_SCRIPT=stage", "LC_STEP=%s" % step, "LC_STAGE=poll",
                "LC_ITEM=%s" % node.item, "LC_WORKFLOW_ORIGIN=acme", "LC_WORKFLOW_NAME=build",
                "LC_WORKFLOW_SHA=%s" % self.sha, "LC_WORKFLOW_CONFIG_API_TOKEN=tok"):
            self.assertIn(expected, env)
        self.assertNotIn("LC_WORKFLOW_HOOK", env)
        self.assertIn("look at the sheet", Path(self.data_dir(), "stdin.json").read_text())

    def test_each_failure_case_parks_with_a_readable_reason(self):
        cases = {
            "crash": ("exited 4", "boom: bad token"),
            "garbage": ("not one JSON object", "not json"),
            "undeclared": ("zzz", "not declared"),
        }
        for mode, needles in cases.items():
            with self.subTest(mode):
                self.set_mode(mode)
                step = self.new_step()

                node = self.drive(step, lambda n: n.role == "human")

                for needle in ("poll", "scripts/poll.sh") + needles:
                    self.assertIn(needle, node.park.reason)

    def test_a_timeout_parks_the_step(self):
        class ShortTimeout:
            def __init__(self, inner):
                self._inner = inner

            def __getattr__(self, name):
                return getattr(self._inner, name)

            def script_timeout_seconds(self):
                return 1

        self.gate._config = ShortTimeout(self.config)
        self.set_mode("slow")
        step = self.new_step()

        node = self.drive(step, lambda n: n.role == "human")

        self.assertIn("timed out after 1s", node.park.reason)


class TestRealGuard(ScratchHome):
    def setUp(self):
        super().setUp()
        self.add()
        c = self.container
        c.store.add_project("acme/app", shortcode="APP", local_path=self.home)
        self.activate = RecordingActivate(c.store)
        self.cadence = ScheduleCadenceUseCase(
            c.store, self.config, c.flow_service(), c.workflow_source, c.git, self.activate,
            c.script_runner, c.workflow_lifecycle())
        self.now = 1_800_000_000.0

    def test_a_passing_script_guard_files_an_item_with_the_printed_title(self):
        Path(self.data_dir(), "guard-mode").write_text("pass")
        err = io.StringIO()
        fired = []
        with contextlib.redirect_stderr(err):
            self.cadence.execute(self.now)
            for _ in range(400):
                fired = self.cadence.execute(self.now).fired
                if fired:
                    break
                time.sleep(0.05)

        self.assertEqual(len(fired), 1)
        item = self.container.store.get_item(fired[0])
        self.assertEqual(item.title, "Sheet changed")

    def test_a_crashing_guard_files_nothing_and_warns_with_its_stderr(self):
        Path(self.data_dir(), "guard-mode").write_text("crash")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.cadence.execute(self.now)
            for _ in range(400):
                self.cadence.execute(self.now)
                if not self.container.script_runner.running():
                    break
                time.sleep(0.05)

        self.assertEqual(self.activate.activated, [])
        self.assertIn("guard boom", err.getvalue())
