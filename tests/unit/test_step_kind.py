import unittest

from lightcycle.domain.audit import AUDIT_STEP, FINDINGS_STEP, StepKind


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


if __name__ == "__main__":
    unittest.main()
