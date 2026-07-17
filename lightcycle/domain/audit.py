from enum import Enum

AUDIT_STEP = "audit"
FINDINGS_STEP = "review-findings"


class StepKind(Enum):
    WORKFLOW = "workflow"
    ENGINE_AUDIT = "engine-audit"
    ENGINE_FINDINGS = "engine-findings"

    @staticmethod
    def of(node):
        if node.step == AUDIT_STEP:
            return StepKind.ENGINE_AUDIT
        if node.step == FINDINGS_STEP:
            return StepKind.ENGINE_FINDINGS
        return StepKind.WORKFLOW
