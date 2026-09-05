import unittest

from lightcycle.domain.audit import AUDIT_STEP, FINDINGS_STEP, StepKind, engine_display_of


class _Node:
    def __init__(self, step):
        self.step = step


class TestStepKind(unittest.TestCase):
    def test_audit_step_is_engine_audit(self):
        self.assertEqual(StepKind.of(_Node(AUDIT_STEP)), StepKind.ENGINE_AUDIT)

    def test_findings_step_is_engine_findings(self):
        self.assertEqual(StepKind.of(_Node(FINDINGS_STEP)), StepKind.ENGINE_FINDINGS)

    def test_named_workflow_step_is_workflow(self):
        self.assertEqual(StepKind.of(_Node("write-code")), StepKind.WORKFLOW)

    def test_stepless_node_is_workflow(self):
        self.assertEqual(StepKind.of(_Node(None)), StepKind.WORKFLOW)


class TestEngineDisplayOf(unittest.TestCase):
    def test_audit_step_phrase(self):
        self.assertEqual(engine_display_of(AUDIT_STEP), "Auditing recent work")

    def test_findings_step_phrase(self):
        self.assertEqual(engine_display_of(FINDINGS_STEP), "Review the findings")

    def test_ordinary_workflow_stage_has_no_engine_phrase(self):
        self.assertIsNone(engine_display_of("write-code"))

    def test_none_step_has_no_engine_phrase(self):
        self.assertIsNone(engine_display_of(None))


if __name__ == "__main__":
    unittest.main()
