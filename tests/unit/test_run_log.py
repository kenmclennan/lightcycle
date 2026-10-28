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
    State,
    guard_log_label,
    hook_log_label,
    script_log_label,
)
from tests.support.fake_fs import FakeFs
from tests.support.fake_store import FakeStore
from tests.support.fake_workers import FakeWorkers
from tests.unit.test_doctor import FakeWorkflowBundle, FakeWorkflowSource, _ALL_KEYS, _cfg, _uc
from lightcycle.application.inspect import DoctorInput


class TestDomain(unittest.TestCase):
    def test_labels_sanitise_unsafe_characters(self):
        self.assertEqual(hook_log_label("acme/x", "my build", "maintain"), "hook-acme_x-my_build-maintain")
        self.assertEqual(script_log_label("LC-1.2"), "script-LC-1.2")
        self.assertEqual(guard_log_label("weekly"), "guard-weekly")


class StepRig(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        self.fs = FakeFs({})
        self.root = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.root, "logs"))
        item = self.store.create_item("t", "d")
        self.item = item
        self.step = self.store.create_step(stage="poll", role="engine", item=item)

    def log_file(self, name="script-x-1.log", text="out\n"):
        path = os.path.join(self.root, "logs", name)
        self.fs.write_text(path, text)
        return path

    def config(self):
        return SimpleNamespace(data_root=lambda: self.root)

    def resolve(self):
        return ResolveLogUseCase(self.store, FakeWorkers(), self.fs, self.config()).execute(
            ResolveLogInput(target=self.step)).path


class TestResolve(StepRig):
    def test_a_recorded_log_that_exists_resolves(self):
        path = self.log_file()
        self.store.set_log(self.step, path)
        self.assertEqual(self.resolve(), path)

    def test_a_recorded_log_that_is_missing_resolves_to_none(self):
        self.store.set_log(self.step, os.path.join(self.root, "gone.log"))
        self.assertIsNone(self.resolve())

    def test_a_later_set_log_replaces_the_earlier_one(self):
        first, second = self.log_file("script-x-1.log"), self.log_file("script-x-2.log")
        self.store.set_log(self.step, first)
        self.store.set_log(self.step, second)
        self.assertEqual(self.resolve(), second)

    def test_a_legacy_log_artifact_is_no_longer_read(self):
        path = self.log_file()
        self.store.add_artifact(self.step, "log", path, internal=True)
        self.assertIsNone(self.resolve())


class TestTail(StepRig):
    def tail(self):
        return TailLogUseCase(self.store, FakeWorkers(), FakeFs({}), self.fs, self.config())

    def test_a_queued_step_with_a_log_is_live_then_not(self):
        path = self.log_file()
        self.store.set_log(self.step, path)
        use_case = TailLogUseCase(self.store, FakeWorkers(), _Reader(), self.fs, self.config())

        self.assertTrue(use_case.execute(TailLogInput(target=self.step)).live)
        self.store.update_state(self.step, State.DONE)
        self.assertFalse(use_case.execute(TailLogInput(target=self.step)).live)


class _Reader:
    def read_from(self, path, offset):
        return b"", offset

    def read_tail(self, path, n):
        return b"", 0


class TestTrace(StepRig):
    def test_a_script_steps_log_field_is_the_recorded_path(self):
        path = self.log_file()
        self.store.set_log(self.step, path)
        resp = TraceUseCase(self.store, FakeWorkers(), self.fs, self.config()).execute(
            TraceInput(item=self.item))
        self.assertEqual(resp.steps[0].log, path)


class TestLogTabMode(StepRig):
    def mode(self, state=None):
        if state is not None:
            self.store.update_state(self.step, state)
        return log_tab_mode(self.store.get_node(self.step))

    def test_engine_step_with_a_log_is_live_while_queued_and_historical_after(self):
        self.store.set_log(self.step, "p")
        self.assertEqual(self.mode(), "live")
        self.assertEqual(self.mode(State.DONE), "historical")

    def test_a_parked_engine_step_with_a_log_is_historical(self):
        node = SimpleNamespace(role="engine", state=State.WAITING, log_path="p")
        self.assertEqual(log_tab_mode(node), "historical")

    def test_engine_step_without_a_log_has_none(self):
        self.assertEqual(self.mode(), "no-log")


class TestDoctorHookFailures(unittest.TestCase):
    def test_open_maintenance_failures_are_reported_with_their_log(self):
        store = FakeStore()
        items = {}
        for name in ("with-log", "no-log", "closed"):
            item = store.create_item("Maintenance failed for %s" % name, "d", shortcode="AUD")
            store.label_add(item, LIFECYCLE_ORIGIN_LABEL)
            step = store.create_step(stage=LIFECYCLE_FAILURE_STEP, role="human", item=item)
            items[name] = (item, step)
        store.set_log(items["with-log"][1], "/logs/hook-a.log")
        store.complete_node(items["closed"][1], "done")
        store.update_state(items["closed"][0], State.DONE)
        source = FakeWorkflowSource()
        source.add_bundle("acme", "sha1", 1, current=True)

        report = _uc(store, source, _cfg(**_ALL_KEYS), FakeWorkflowBundle()).execute(DoctorInput())

        messages = [p.message for p in report.problems["workflows"]]
        self.assertEqual(len(messages), 2)
        self.assertTrue(any(items["with-log"][0] in m and "/logs/hook-a.log" in m for m in messages))
        self.assertTrue(any(items["no-log"][0] in m and "no log recorded" in m for m in messages))
        self.assertFalse(any(items["closed"][0] in m for m in messages))
