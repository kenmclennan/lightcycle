import unittest

from lightcycle.domain.work.artifact import Artifact
from lightcycle.domain.work.outputs import (
    ArtifactRecord,
    StepFacts,
    classify_step_rows,
    resolve_outputs,
)

ITEM = "APP-1"


def facts(step_id, pass_n, declared=("X",)):
    return StepFacts(
        id=step_id, pass_id="APP-1.p%d" % pass_n, declared=frozenset(declared),
        at="t-%s" % step_id)


def rec(node, seq, atype, value, internal=False, label=None):
    return ArtifactRecord(
        node_id=node, seq=seq,
        artifact=Artifact(type=atype, value=value, label=label, internal=internal))


STEPS = {
    "s1": facts("s1", 1),
    "s2": facts("s2", 1),
    "s3": facts("s3", 2),
    "s4": facts("s4", 2),
}
LOG = [
    rec("s1", 10, "X", "v10"),
    rec("s2", 20, "X", "v20"),
    rec("s3", 30, "X", "v30"),
    rec("s4", 31, "R", "r31"),
]


def current(outputs, name="X"):
    return [e.value for e in outputs.artifacts if e.name == name]


def history(outputs, name="X"):
    entry = next(e for e in outputs.artifacts if e.name == name)
    return [h.value for h in outputs.history_of(entry)]


class TestWorkedExample(unittest.TestCase):
    def test_a_pass_1_reader_sees_pass_1_s_newest_and_not_pass_2(self):
        out = resolve_outputs(ITEM, LOG, STEPS, reader_pass=1)
        self.assertEqual(current(out), ["v20"])
        self.assertEqual(history(out), ["v10"])

    def test_a_pass_2_reader_before_s3_ran_sees_the_same_as_pass_1(self):
        log = [r for r in LOG if r.node_id != "s3"]
        out = resolve_outputs(ITEM, log, STEPS, reader_pass=2)
        self.assertEqual(current(out), ["v20"])
        self.assertEqual(history(out), ["v10"])

    def test_a_pass_2_reader_after_s3_sees_the_boundary_row_as_current(self):
        out = resolve_outputs(ITEM, LOG, STEPS, reader_pass=2)
        self.assertEqual(current(out), ["v30"])
        self.assertEqual(history(out), ["v20", "v10"])

    def test_an_item_view_with_no_pass_sees_everything(self):
        out = resolve_outputs(ITEM, LOG, STEPS, reader_pass=None)
        self.assertEqual(current(out), ["v30"])
        self.assertEqual(history(out), ["v20", "v10"])

    def test_an_undeclared_attach_is_never_an_output(self):
        for reader in (1, 2, None):
            out = resolve_outputs(ITEM, LOG, STEPS, reader_pass=reader)
            self.assertEqual(current(out, "R"), [], reader)


class TestIdentityAndPrecedence(unittest.TestCase):
    def test_an_item_attached_row_beats_a_newer_step_row_which_becomes_history(self):
        log = [rec(ITEM, 5, "X", "item"), rec("s1", 10, "X", "step")]
        out = resolve_outputs(ITEM, log, STEPS, reader_pass=None)
        self.assertEqual(current(out), ["item"])
        self.assertEqual(history(out), ["step"])

    def test_labels_are_separate_identities(self):
        log = [rec("s1", 10, "X", "a", label="one"), rec("s2", 20, "X", "b", label="two")]
        out = resolve_outputs(ITEM, log, STEPS, reader_pass=None)
        self.assertEqual(sorted(current(out)), ["a", "b"])
        self.assertEqual(out.history, {})

    def test_an_internal_attach_of_a_declared_type_is_not_an_output(self):
        log = [rec("s1", 10, "X", "hidden", internal=True)]
        out = resolve_outputs(ITEM, log, STEPS, reader_pass=None)
        self.assertEqual(current(out), [])

    def test_a_step_whose_workflow_declares_nothing_contributes_no_outputs(self):
        steps = dict(STEPS, s1=facts("s1", 1, declared=()))
        out = resolve_outputs(ITEM, LOG, steps, reader_pass=None)
        self.assertEqual(current(out), ["v30"])
        self.assertEqual(history(out), ["v20"])

    def test_bookkeeping_rows_are_never_outputs_even_if_declared(self):
        steps = {"s1": facts("s1", 1, declared=("session-id",))}
        out = resolve_outputs(ITEM, [rec("s1", 1, "session-id", "abc")], steps)
        self.assertEqual(out.artifacts, ())

    def test_by_step_groups_current_entries(self):
        out = resolve_outputs(ITEM, LOG, STEPS, reader_pass=None)
        self.assertEqual(list(out.by_step()), ["s3"])
        self.assertEqual(out.types, {"X"})


class TestClassification(unittest.TestCase):
    def test_mixed_rows_split_into_outputs_and_records(self):
        rows = [
            Artifact(type="X", value="1"),
            Artifact(type="R", value="2"),
            Artifact(type="X", value="3", internal=True),
            Artifact(type="session-id", value="s"),
            Artifact(type="reflection", value="r", internal=True),
        ]
        outputs, records = classify_step_rows(rows, frozenset({"X"}))
        self.assertEqual([a.value for a in outputs], ["1"])
        self.assertEqual([a.value for a in records], ["2", "3", "r"])


if __name__ == "__main__":
    unittest.main()
