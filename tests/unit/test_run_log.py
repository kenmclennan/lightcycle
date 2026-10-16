import os
import tempfile
import unittest
from types import SimpleNamespace

from lightcycle.adapters.tui.hub import log_tab_mode
from lightcycle.application.flow.engine_steps import (
    LIFECYCLE_FAILURE_STEP,
    LIFECYCLE_ORIGIN_LABEL,
)
from lightcycle.application.pool.resolve_log import ResolveLogInput, ResolveLogUseCase
from lightcycle.application.pool.tail_log import TailLogInput, TailLogUseCase
from lightcycle.application.work import TraceInput, TraceUseCase
from lightcycle.domain.work import (
    LOG_ARTIFACT,
    State,
    guard_log_label,
    hook_log_label,
    latest_log_path,
    script_log_label,
)
from tests.support.fake_fs import FakeFs
from tests.support.fake_store import FakeStore
from tests.support.fake_workers import FakeWorkers
from tests.unit.test_doctor import FakeWorkflowBundle, FakeWorkflowSource, _ALL_KEYS, _cfg, _uc
from lightcycle.application.inspect import DoctorInput


def art(value, atype=LOG_ARTIFACT):
    return SimpleNamespace(type=atype, value=value)


class TestDomain(unittest.TestCase):
    def test_latest_log_path_is_none_for_no_log_artifact(self):
        self.assertIsNone(latest_log_path([]))
        self.assertIsNone(latest_log_path([art("x", "spec")]))

    def test_latest_log_path_is_the_last_log_artifact(self):
        self.assertEqual(latest_log_path([art("a")]), "a")
        self.assertEqual(latest_log_path([art("a"), art("z", "spec"), art("b")]), "b")

    def test_labels_sanitise_unsafe_characters(self):
        self.assertEqual(hook_log_label("acme/x", "my build", "maintain"), "hook-acme_x-my_build-maintain")
        self.assertEqual(script_log_label("LC-1.2"), "script-LC-1.2")
        self.assertEqual(guard_log_label("weekly"), "guard-weekly")


class StepRig(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        self.root = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.root, "logs"))
        item = self.store.create_item("t", "d")
        self.item = item
        self.step = self.store.create_step(step="poll", role="engine", parent=item)

    def log_file(self, name="script-x-1.log", text="out\n"):
        path = os.path.join(self.root, "logs", name)
        with open(path, "w") as f:
            f.write(text)
        return path

    def config(self):
        return SimpleNamespace(data_root=lambda: self.root)

    def resolve(self):
        return ResolveLogUseCase(self.store, FakeWorkers(), self.config()).execute(
            ResolveLogInput(target=self.step)).path


class TestResolve(StepRig):
    def test_a_recorded_log_that_exists_resolves(self):
        path = self.log_file()
        self.store.add_artifact(self.step, LOG_ARTIFACT, path, internal=True)
        self.assertEqual(self.resolve(), path)

    def test_a_recorded_log_that_is_missing_resolves_to_none(self):
        self.store.add_artifact(self.step, LOG_ARTIFACT, os.path.join(self.root, "gone.log"))
        self.assertIsNone(self.resolve())

    def test_the_later_of_two_artifacts_wins(self):
        first, second = self.log_file("script-x-1.log"), self.log_file("script-x-2.log")
        self.store.add_artifact(self.step, LOG_ARTIFACT, first, internal=True)
        self.store.add_artifact(self.step, LOG_ARTIFACT, second, internal=True)
        self.assertEqual(self.resolve(), second)


class TestTail(StepRig):
    def tail(self):
        return TailLogUseCase(self.store, FakeWorkers(), FakeFs({}), self.config())

    def test_a_queued_step_with_a_log_is_live_then_not(self):
        path = self.log_file()
        self.store.add_artifact(self.step, LOG_ARTIFACT, path, internal=True)
        use_case = TailLogUseCase(self.store, FakeWorkers(), _Reader(), self.config())

        self.assertTrue(use_case.execute(TailLogInput(target=self.step)).live)
        self.store.update_state(self.step, State.DONE)
        self.assertFalse(use_case.execute(TailLogInput(target=self.step)).live)


class _Reader:
    def read_from(self, path, offset):
        return b"", offset

    def read_tail(self, path, n):
        return b"", 0


class TestTrace(StepRig):
    def test_a_script_steps_log_field_is_the_artifact_path(self):
        path = self.log_file()
        self.store.add_artifact(self.step, LOG_ARTIFACT, path, internal=True)
        resp = TraceUseCase(self.store, FakeWorkers(), self.config()).execute(
            TraceInput(item=self.item))
        self.assertEqual(resp.steps[0].log, path)


class TestLogTabMode(StepRig):
    def mode(self, state=None):
        if state is not None:
            self.store.update_state(self.step, state)
        return log_tab_mode(
            self.store.get_node(self.step), self.store.item_artifacts(self.step))

    def test_engine_step_with_a_log_is_live_while_queued_and_historical_after(self):
        self.store.add_artifact(self.step, LOG_ARTIFACT, "p", internal=True)
        self.assertEqual(self.mode(), "live")
        self.assertEqual(self.mode(State.DONE), "historical")

    def test_a_parked_engine_step_with_a_log_is_historical(self):
        node = SimpleNamespace(role="engine", state=State.WAITING)
        self.assertEqual(log_tab_mode(node, [art("p")]), "historical")

    def test_engine_step_without_a_log_has_none(self):
        self.assertEqual(self.mode(), "no-log")


class TestDoctorHookFailures(unittest.TestCase):
    def test_open_maintenance_failures_are_reported_with_their_log(self):
        store = FakeStore()
        items = {}
        for name in ("with-log", "no-log", "closed"):
            item = store.create_item("Maintenance failed for %s" % name, "d", shortcode="AUD")
            store.label_add(item, LIFECYCLE_ORIGIN_LABEL)
            step = store.create_step(step=LIFECYCLE_FAILURE_STEP, role="human", parent=item)
            items[name] = (item, step)
        store.add_artifact(items["with-log"][0], LOG_ARTIFACT, "/logs/hook-a.log")
        store.complete_node(items["closed"][1], "done")
        store.update_state(items["closed"][0], State.DONE)
        source = FakeWorkflowSource()
        source.add_bundle("acme", "sha1", 1, current=True)

        report = _uc(store, source, _cfg(**_ALL_KEYS), FakeWorkflowBundle()).execute(DoctorInput())

        messages = [p.message for p in report.problems["origin"]]
        self.assertEqual(len(messages), 2)
        self.assertTrue(any(items["with-log"][0] in m and "/logs/hook-a.log" in m for m in messages))
        self.assertTrue(any(items["no-log"][0] in m and "no log recorded" in m for m in messages))
        self.assertFalse(any(items["closed"][0] in m for m in messages))
