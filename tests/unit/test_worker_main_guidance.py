import contextlib
import io
import types
import unittest

from lightcycle.adapters.worker_session import SessionPlan, record_guidance
from tests.support.fake_store import FakeStore


def _record(plan, store):
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        record_guidance(store, plan)
    return err.getvalue()


class TestRecordGuidance(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        item = self.store.create_item("t", "d")
        self.step = self.store.create_step(step="build", role="agent", parent=item)

    def _artifacts(self):
        return {a.type: a.value for a in self.store.item_artifacts(self.step)}

    def test_records_ids_in_order_joined_by_newline(self):
        plan = SessionPlan(model="m", sysprompt="s", step_id=self.step,
                           guidance_delivered=("a/b", "c"), guidance_skipped=("d",),
                           guidance_recorded=True)
        self.assertEqual(_record(plan, self.store), "")
        self.assertEqual(self._artifacts()["guidance-delivered"], "a/b\nc")
        self.assertEqual(self._artifacts()["guidance-skipped"], "d")

    def test_no_matches_records_an_empty_delivered_value(self):
        plan = SessionPlan(model="m", sysprompt="s", step_id=self.step, guidance_recorded=True)
        _record(plan, self.store)
        self.assertEqual(self._artifacts()["guidance-delivered"], "")

    def test_notes_are_written_one_line_each_to_stderr(self):
        plan = SessionPlan(model="m", sysprompt="s", step_id=self.step,
                           guidance_notes=("one", "two"), guidance_recorded=True)
        self.assertEqual(
            _record(plan, self.store),
            "worker_main: guidance: one\nworker_main: guidance: two\n")

    def test_a_failed_selection_writes_its_line_and_records_nothing(self):
        plan = SessionPlan(model="m", sysprompt="s", step_id=self.step,
                           guidance_notes=("kaboom",), guidance_recorded=False)
        self.assertEqual(_record(plan, self.store), "worker_main: guidance: kaboom\n")
        self.assertEqual(self._artifacts(), {})

    def test_a_recording_failure_is_one_line_and_does_not_raise(self):
        store = types.SimpleNamespace(
            replace_artifact=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db gone")))
        plan = SessionPlan(model="m", sysprompt="s", step_id=self.step, guidance_recorded=True)
        self.assertEqual(_record(plan, store), "worker_main: guidance: db gone\n")


if __name__ == "__main__":
    unittest.main()
