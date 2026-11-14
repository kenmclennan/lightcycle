import json
import unittest
from types import SimpleNamespace

from lightcycle.application.work.step_detail import StepDetail
from lightcycle.domain.flow.flow import Flow
from lightcycle.domain.flow.step_def import StepDef
from lightcycle.domain.work.callout_runs import CALLOUT_RUNS
from lightcycle.domain.work.detail import DetailEntry, callout_entries
from tests.support.fake_store import FakeStore


class _Flow:
    def flow_for(self, node):
        return Flow({"gate": StepDef(presents="pr", detail=("outcome", "report"), phase="code")})

    def phase_for(self, node):
        return None


def resolve(store, step):
    run = SimpleNamespace(pr=None, branch=None, pass_id=None, phase=None, item=None)
    return StepDetail(store, _Flow()).resolve(store.get_node(step), {}, [], run=run)


def planted(runs):
    store = FakeStore()
    item = store.create_item("t", "d", shortcode="APP")
    step = store.create_step(stage="gate", role="human", item=item)
    if runs is not None:
        store.replace_artifact(step, CALLOUT_RUNS, json.dumps(runs), internal=True)
    return store, step


class TestCalloutRows(unittest.TestCase):
    def test_rows_follow_the_workflows_names_and_presents_is_unchanged(self):
        store, step = planted({"a": {"status": "running"}})

        entries, presents = resolve(store, step)

        self.assertEqual([e.key for e in entries], ["outcome", "report", "callout:a"])
        self.assertEqual(presents, "outcome")

    def test_running_failed_and_ok_rows(self):
        runs = {
            "r": {"status": "running"},
            "f": {"status": "failed", "message": "boom"},
            "o": {"status": "ok", "artifacts": [
                {"label": "Open", "kind": "link", "value": "myapp://x"},
                {"label": "Note", "kind": "markdown", "value": "# hi"}]},
            "e": {"status": "ok", "artifacts": []},
        }
        rows = callout_entries(runs)

        self.assertEqual([(e.key, e.value, e.label, e.artifact_kind) for e in rows], [
            ("callout:r", "running", "callout:r", None),
            ("callout:f", "failed: boom", "callout:f", None),
            ("callout:o:1", "myapp://x", "Open", "link"),
            ("callout:o:2", "# hi", "Note", "markdown")])

    def test_a_failed_record_with_errors_adds_one_row_per_error(self):
        errors = [{"message": "m1", "fix": "f1"}, {"message": "m2", "fix": "f2"}]
        rows = callout_entries({"a": {"status": "failed", "message": "m1 (and 1 more)", "errors": errors}})

        self.assertEqual([(e.key, e.value, e.label, e.artifact_kind) for e in rows], [
            ("callout:a", "failed: m1 (and 1 more)", "callout:a", None),
            ("callout:a:error:1", "m1 - fix: f1", "callout:a:error:1", None),
            ("callout:a:error:2", "m2 - fix: f2", "callout:a:error:2", None)])

    def test_a_failed_record_without_errors_renders_as_before(self):
        rows = callout_entries({"a": {"status": "failed", "message": "boom"}})

        self.assertEqual([e.key for e in rows], ["callout:a"])

    def test_a_step_with_no_record_has_byte_identical_rows(self):
        store, step = planted(None)

        entries, _ = resolve(store, step)

        self.assertEqual(
            [e.as_dict() for e in entries],
            [{"key": "outcome", "kind": "field", "value": None},
             {"key": "report", "kind": "field", "value": None}])

    def test_as_dict_adds_label_and_artifact_kind_only_when_set(self):
        plain = DetailEntry(key="k", kind="field", value="v")
        rich = DetailEntry(key="k", kind="callout", value="v", label="L", artifact_kind="link")

        self.assertEqual(set(plain.as_dict()), {"key", "kind", "value"})
        self.assertEqual(rich.as_dict()["label"], "L")
        self.assertEqual(rich.as_dict()["artifact_kind"], "link")
