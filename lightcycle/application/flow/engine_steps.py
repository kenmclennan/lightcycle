from enum import Enum

from lightcycle.domain.feedback import RETRO_ORIGIN_LABEL as RETRO_ORIGIN_LABEL

AUDIT_STEP = "audit"
FINDINGS_STEP = "review-findings"
SUMMARY_ORIGIN_LABEL = "summary-origin"
DAILY_SUMMARY_STEP = "daily-summary"

ENGINE_STEP_DISPLAY = {
    AUDIT_STEP: "Auditing recent work",
    FINDINGS_STEP: "Review the findings",
    DAILY_SUMMARY_STEP: "Writing the daily summary",
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
