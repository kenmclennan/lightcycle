from enum import Enum

from lightcycle.domain.feedback import HELD_COMMENT_ORIGIN_LABEL as HELD_COMMENT_ORIGIN_LABEL
from lightcycle.domain.feedback import RETRO_ORIGIN_LABEL as RETRO_ORIGIN_LABEL

AUDIT_STEP = "audit"
MATERIAL_AUDIT_STEP = "material-audit"
FINDINGS_STEP = "review-findings"
SUMMARY_ORIGIN_LABEL = "summary-origin"
DAILY_SUMMARY_STEP = "daily-summary"
HELD_COMMENT_STEP = "review-held-comment"

ENGINE_STEP_DISPLAY = {
    AUDIT_STEP: "Auditing recent work",
    MATERIAL_AUDIT_STEP: "Auditing guidance and workflows",
    FINDINGS_STEP: "Review the findings",
    DAILY_SUMMARY_STEP: "Writing the daily summary",
    HELD_COMMENT_STEP: "Decide whether a held comment counts",
}

ENGINE_STEP_OUTCOMES = {
    AUDIT_STEP: ("findings", "clean"),
    MATERIAL_AUDIT_STEP: ("findings", "clean"),
    FINDINGS_STEP: ("done", "filed", "reviewed"),
    DAILY_SUMMARY_STEP: ("done", "abandoned"),
    HELD_COMMENT_STEP: ("approve", "reject"),
}


def engine_display_of(step):
    return ENGINE_STEP_DISPLAY.get(step)


def engine_outcomes_of(step):
    return ENGINE_STEP_OUTCOMES.get(step)


def engine_outcomes_for_node(store, node):
    labels = store.labels_of(node.item)
    if node.stage in (AUDIT_STEP, MATERIAL_AUDIT_STEP, FINDINGS_STEP) and RETRO_ORIGIN_LABEL in labels:
        return engine_outcomes_of(node.stage)
    if node.stage == DAILY_SUMMARY_STEP and SUMMARY_ORIGIN_LABEL in labels:
        return engine_outcomes_of(node.stage)
    if node.stage == HELD_COMMENT_STEP and HELD_COMMENT_ORIGIN_LABEL in labels:
        return engine_outcomes_of(node.stage)
    return None


class StepKind(Enum):
    WORKFLOW = "workflow"
    ENGINE_FINDINGS = "engine-findings"

    @staticmethod
    def of(node):
        if node.stage == FINDINGS_STEP:
            return StepKind.ENGINE_FINDINGS
        return StepKind.WORKFLOW
