import unittest

from lightcycle.domain.runs import PhaseRun
from lightcycle.domain.work.artifact import Artifact
from lightcycle.domain.work.output_rows import output_lines, output_rows
from lightcycle.domain.work.outputs import ArtifactRecord, StepFacts, resolve_outputs

ITEM = "LC-1"


def _record(node, seq, atype, value, label=None, internal=False):
    return ArtifactRecord(node, seq, Artifact(type=atype, value=value, label=label, internal=internal))


def _facts(step, pass_id, declared=("spec",), at="t"):
    return StepFacts(id=step, pass_id=pass_id, declared=frozenset(declared), at=at)


def _run(pass_id, phase, pr, opened_at):
    return PhaseRun("%s.%s" % (pass_id, phase), ITEM, pass_id, phase, pr=pr, opened_at=opened_at)


class TestOutputRows(unittest.TestCase):
    def test_current_row_carries_producing_step_and_pass_with_history_newest_first(self):
        records = [
            _record("LC-1.1", 1, "spec", "v1"),
            _record("LC-1.2", 2, "spec", "v2"),
            _record("LC-1.3", 3, "spec", "v3"),
        ]
        steps = {
            "LC-1.1": _facts("LC-1.1", "LC-1.p1"),
            "LC-1.2": _facts("LC-1.2", "LC-1.p2"),
            "LC-1.3": _facts("LC-1.3", "LC-1.p3"),
        }
        rows = output_rows(resolve_outputs(ITEM, records, steps), [])
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual((row.name, row.value, row.step, row.pass_id), ("spec", "v3", "LC-1.3", "LC-1.p3"))
        self.assertEqual([h.value for h in row.history], ["v2", "v1"])

    def test_item_attached_row_wins_over_a_step_row_and_has_no_step(self):
        records = [
            _record(ITEM, 1, "spec", "attached"),
            _record("LC-1.1", 2, "spec", "from-step"),
        ]
        steps = {"LC-1.1": _facts("LC-1.1", "LC-1.p1")}
        rows = output_rows(resolve_outputs(ITEM, records, steps), [])
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0].value, rows[0].step, rows[0].pass_id), ("attached", None, None))
        self.assertEqual([h.value for h in rows[0].history], ["from-step"])

    def test_pr_rows_are_one_per_phase_ordered_by_opened_at_after_the_outputs(self):
        records = [_record("LC-1.1", 1, "spec", "v1")]
        steps = {"LC-1.1": _facts("LC-1.1", "LC-1.p1")}
        runs = [
            _run("LC-1.p1", "code", "https://gh/pr/2", "2026-01-02"),
            _run("LC-1.p1", "spec", "https://gh/pr/1", "2026-01-01"),
        ]
        rows = output_rows(resolve_outputs(ITEM, records, steps), runs)
        self.assertEqual([(r.name, r.label, r.value) for r in rows], [
            ("spec", None, "v1"), ("pr", "spec", "https://gh/pr/1"), ("pr", "code", "https://gh/pr/2"),
        ])
        self.assertEqual({r.kind for r in rows[1:]}, {"url"})
        self.assertEqual(rows[1].step, "spec")
        self.assertEqual(rows[1].pass_id, "LC-1.p1")

    def test_a_reworked_pr_phase_keeps_the_latest_run_current_and_the_earlier_as_history(self):
        runs = [
            _run("LC-1.p1", "code", "https://gh/pr/2", "2026-01-01"),
            _run("LC-1.p2", "code", "https://gh/pr/9", "2026-01-05"),
        ]
        rows = output_rows(resolve_outputs(ITEM, [], {}), runs)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].value, "https://gh/pr/9")
        self.assertEqual([(h.value, h.pass_id) for h in rows[0].history], [("https://gh/pr/2", "LC-1.p1")])

    def test_a_single_pr_run_has_no_history_and_no_older_marker(self):
        runs = [_run("LC-1.p1", "code", "https://gh/pr/2", "2026-01-01")]
        rows = output_rows(resolve_outputs(ITEM, [], {}), runs)
        self.assertEqual(rows[0].history, ())
        self.assertEqual(output_lines(rows, {rows[0].key})[0].older, 0)
        self.assertEqual(len(output_lines(rows, {rows[0].key})), 1)

    def test_runs_without_a_pr_produce_no_row(self):
        runs = [_run("LC-1.p1", "spec", None, "2026-01-01")]
        self.assertEqual(output_rows(resolve_outputs(ITEM, [], {}), runs), [])

    def test_records_and_bookkeeping_never_appear(self):
        records = [
            _record("LC-1.1", 1, "reflection", "x", internal=True),
            _record("LC-1.1", 2, "session-id", "abc"),
            _record(ITEM, 3, "resolves", "LC-9", internal=True),
        ]
        steps = {"LC-1.1": _facts("LC-1.1", "LC-1.p1", declared=("reflection", "session-id"))}
        self.assertEqual(output_rows(resolve_outputs(ITEM, records, steps), []), [])


class TestOutputLines(unittest.TestCase):
    def _rows(self):
        records = [_record("LC-1.1", 1, "spec", "v1"), _record("LC-1.2", 2, "spec", "v2")]
        steps = {"LC-1.1": _facts("LC-1.1", "LC-1.p1"), "LC-1.2": _facts("LC-1.2", "LC-1.p2")}
        return output_rows(resolve_outputs(ITEM, records, steps), [])

    def test_collapsed_row_shows_only_current_with_the_older_count(self):
        lines = output_lines(self._rows(), set())
        self.assertEqual([(l.value, l.older, l.is_history) for l in lines], [("v2", 1, False)])

    def test_expanded_row_lists_earlier_versions_directly_under_it(self):
        lines = output_lines(self._rows(), {"spec"})
        self.assertEqual(
            [(l.value, l.is_history, l.pass_text) for l in lines],
            [("v2", False, "p2"), ("v1", True, "p1")],
        )

    def test_history_line_opens_as_its_own_version(self):
        lines = output_lines(self._rows(), {"spec"})
        self.assertEqual(lines[1].as_artifact().value, "v1")


if __name__ == "__main__":
    unittest.main()
