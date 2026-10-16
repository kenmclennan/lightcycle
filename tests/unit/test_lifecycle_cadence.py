import contextlib
import datetime
import io
import unittest

from lightcycle.application.flow.complete_step import CompleteInput, CompleteStepUseCase
from lightcycle.application.flow.engine_steps import (
    LIFECYCLE_FAILURE_STEP,
    LIFECYCLE_ORIGIN_LABEL,
)
from lightcycle.application.pool.lifecycle_cadence import LifecycleCadenceUseCase
from lightcycle.domain.work import Lane, State, lane_for
from lightcycle.ports.lifecycle_runner import HookResult
from tests.support.fake_lifecycle_runner import FakeLifecycleRunner
from tests.support.lifecycle_fakes import lifecycle_for
from tests.unit.test_workflow_lifecycle_usecases import (
    Harness,
    PinnedBundles,
    workflow_text,
)

KEY = "acme/build"


def at(day, hour=3, minute=0, second=0):
    return datetime.datetime(2026, 1, day, hour, minute, second).timestamp()


def naive(day, hour=3, minute=0):
    return datetime.datetime(2026, 1, day, hour, minute)


class CadenceFixture(unittest.TestCase):
    def build(self, blocks=None, workflows=None, due=None):
        self.h = Harness(blocks=blocks)
        self.h.remote("sha1", workflows or {
            "build": workflow_text(install=False, upgrade=False, maintain=True)})
        self.h.add()
        self.h.runner.calls.clear()
        if due is not None:
            self.h.runner.due.update(due)
        return self.gate_over(self.h.runner)

    def gate_over(self, runner):
        self.runner = runner
        lifecycle = lifecycle_for(
            self.h.source, bundle=PinnedBundles(self.h.source),
            config=self.h.lifecycle._config, runner=runner)
        return LifecycleCadenceUseCase(
            self.h.store, self.h.lifecycle._config, self.h.source, lifecycle, runner,
            lambda: "AUD")

    def execute(self, gate, now):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            result = gate.execute(now)
        return result, err.getvalue()

    def failure_items(self):
        return self.h.store.items_with_label(LIFECYCLE_ORIGIN_LABEL)


class TestDueness(CadenceFixture):
    def test_no_record_means_record_and_start_nothing(self):
        gate = self.build()
        result, _ = self.execute(gate, at(2, 3, 0, 5))
        self.assertEqual(result.started, [])
        self.assertEqual(self.runner.due[KEY], naive(2))
        self.assertEqual(self.runner.started, [])

    def test_a_tick_at_the_recorded_due_time_does_not_run(self):
        gate = self.build(due={KEY: naive(1)})
        result, _ = self.execute(gate, at(1, 3, 0, 5))
        self.assertEqual(result.started, [])

    def test_the_exact_due_minute_starts_and_a_later_second_does_not(self):
        gate = self.build(due={KEY: naive(1)})
        first, _ = self.execute(gate, at(2, 3, 0, 0))
        self.assertEqual(first.started, [KEY])
        self.runner.finish(KEY, HookResult(exit_code=0))
        self.execute(gate, at(2, 3, 0, 1))
        again, _ = self.execute(gate, at(2, 3, 0, 5))
        self.assertEqual(again.started, [])
        self.assertEqual(len(self.runner.started), 1)

    def test_a_restart_after_missed_due_times_starts_exactly_once(self):
        self.build(due={KEY: naive(2)})
        shared = self.runner.due
        restarted = self.gate_over(FakeLifecycleRunner(due=shared))
        result, _ = self.execute(restarted, at(5, 9, 0))
        self.assertEqual(result.started, [KEY])
        self.assertEqual(self.runner.due[KEY], naive(5))
        self.runner.finish(KEY, HookResult(exit_code=0))
        self.execute(restarted, at(5, 9, 1))
        second, _ = self.execute(restarted, at(5, 9, 2))
        self.assertEqual(second.started, [])
        self.assertEqual(len(self.runner.started), 1)

    def test_reset_leaves_the_record_alone(self):
        gate = self.build(due={KEY: naive(1)})
        gate.reset()
        self.assertEqual(self.runner.due[KEY], naive(1))

    def test_a_missing_required_key_warns_once_and_records_nothing(self):
        gate = self.build(blocks={"workflow-acme-build": {}}, due={KEY: naive(1)})
        first, err = self.execute(gate, at(2, 3, 0, 0))
        self.assertEqual(first.started, [])
        self.assertEqual(err.count("missing required config key(s) api-token"), 1)
        self.assertEqual(self.runner.due[KEY], naive(1))
        _, err_again = self.execute(gate, at(2, 3, 1, 0))
        self.assertEqual(err_again, "")

    def test_the_started_process_gets_the_data_dir_config_and_timeout(self):
        gate = self.build(due={KEY: naive(1)})
        self.execute(gate, at(2, 3, 0, 0))
        key, call = self.runner.started[0]
        self.assertEqual(key, KEY)
        self.assertEqual(call["env"]["LC_WORKFLOW_HOOK"], "maintain")
        self.assertEqual(call["env"]["LC_WORKFLOW_CONFIG_API_TOKEN"], "tok")
        self.assertEqual(call["cwd"], "/data/workflow-data/acme/build")
        self.assertEqual(call["script"], "acme/sha1/scripts/maintain.sh")
        self.assertEqual(call["timeout"], 300)


class TestBackground(CadenceFixture):
    def test_the_starting_tick_returns_while_the_process_runs(self):
        gate = self.build(due={KEY: naive(1)})
        result, _ = self.execute(gate, at(2, 3, 0, 0))
        self.assertEqual(result.started, [KEY])
        self.assertEqual(gate.in_flight(), [KEY])
        later, _ = self.execute(gate, at(2, 3, 1, 0))
        self.assertEqual((later.started, later.reaped), ([], []))
        self.assertEqual(len(self.runner.started), 1)
        self.assertEqual(gate.in_flight(), [KEY])

    def test_a_non_zero_exit_files_one_item_at_reap_time(self):
        gate = self.build(due={KEY: naive(1)})
        self.execute(gate, at(2, 3, 0, 0))
        self.runner.finish(KEY, HookResult(exit_code=1, output="oops"))
        result, _ = self.execute(gate, at(2, 3, 1, 0))
        self.assertEqual(result.reaped, [KEY])
        self.assertEqual(len(result.filed), 1)
        self.assertEqual(gate.in_flight(), [])
        item = self.failure_items()[0]
        self.assertIn("acme/build", item.title)
        self.assertIn("exited 1: oops", item.description)
        self.assertTrue(item.id.startswith("AUD"))

    def test_a_timeout_files_one_item(self):
        gate = self.build(due={KEY: naive(1)})
        self.execute(gate, at(2, 3, 0, 0))
        self.runner.finish(KEY, HookResult(exit_code=None, timed_out=True))
        self.execute(gate, at(2, 3, 1, 0))
        self.assertEqual(len(self.failure_items()), 1)
        self.assertIn("timed out", self.failure_items()[0].description)

    def test_a_zero_exit_files_nothing(self):
        gate = self.build(due={KEY: naive(1)})
        self.execute(gate, at(2, 3, 0, 0))
        self.runner.finish(KEY, HookResult(exit_code=0))
        result, _ = self.execute(gate, at(2, 3, 1, 0))
        self.assertEqual((result.reaped, result.filed), ([KEY], []))
        self.assertEqual(self.failure_items(), [])

    def test_the_failure_step_is_a_human_inbox_step(self):
        gate = self.build(due={KEY: naive(1)})
        self.execute(gate, at(2, 3, 0, 0))
        self.runner.finish(KEY, HookResult(exit_code=1))
        self.execute(gate, at(2, 3, 1, 0))
        item = self.failure_items()[0]
        steps = self.h.store.children(item.id)
        self.assertEqual([(s.stage, s.role) for s in steps], [(LIFECYCLE_FAILURE_STEP, "human")])
        self.assertEqual(lane_for(steps[0].state), Lane.INBOX)
        self.assertIn("lifecycle:%s" % KEY, self.h.store.labels_of(item.id))

    def test_a_second_failure_while_open_files_none_and_done_allows_the_next(self):
        gate = self.build(due={KEY: naive(1)})
        self.execute(gate, at(2, 3, 0, 0))
        self.runner.finish(KEY, HookResult(exit_code=1))
        self.execute(gate, at(2, 3, 1, 0))
        self.execute(gate, at(3, 3, 0, 0))
        self.runner.finish(KEY, HookResult(exit_code=1))
        self.execute(gate, at(3, 3, 1, 0))
        self.assertEqual(len(self.failure_items()), 1)
        step = self.h.store.children(self.failure_items()[0].id)[0]
        CompleteStepUseCase(self.h.store, None).execute(
            CompleteInput(step=step.id, outcome="done"))
        self.assertEqual(self.h.store.get_node(step.id).state, State.DONE)
        self.execute(gate, at(4, 3, 0, 0))
        self.runner.finish(KEY, HookResult(exit_code=1))
        self.execute(gate, at(4, 3, 1, 0))
        self.assertEqual(len(self.failure_items()), 2)

    def test_two_workflows_due_together_file_one_item_for_the_failing_one(self):
        gate = self.build(
            blocks={
                "workflow-acme-build": {"api-token": "tok"},
                "workflow-acme-ship": {"api-token": "tok"},
            },
            workflows={
                "build": workflow_text(install=False, upgrade=False, maintain=True),
                "ship": workflow_text(install=False, upgrade=False, maintain=True),
            },
            due={KEY: naive(1), "acme/ship": naive(1)})
        result, _ = self.execute(gate, at(2, 3, 0, 0))
        self.assertEqual(sorted(result.started), ["acme/build", "acme/ship"])
        self.runner.finish("acme/build", HookResult(exit_code=0))
        self.runner.finish("acme/ship", HookResult(exit_code=1, output="bad"))
        reaped, _ = self.execute(gate, at(2, 3, 1, 0))
        self.assertEqual(len(reaped.filed), 1)
        items = self.failure_items()
        self.assertEqual(len(items), 1)
        self.assertIn("acme/ship", items[0].title)
