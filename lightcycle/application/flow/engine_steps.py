from enum import Enum

RETRO_ORIGIN_LABEL = "retro-origin"
AUDIT_STEP = "audit"
FINDINGS_STEP = "review-findings"

ENGINE_STEP_DISPLAY = {
    AUDIT_STEP: "Auditing recent work",
    FINDINGS_STEP: "Review the findings",
}


def engine_display_of(step):
    return ENGINE_STEP_DISPLAY.get(step)


class StepKind(Enum):
    WORKFLOW = "workflow"
    ENGINE_FINDINGS = "engine-findings"

    @staticmethod
    def of(node):
        if node.stage == FINDINGS_STEP:
            return StepKind.ENGINE_FINDINGS
        return StepKind.WORKFLOW
