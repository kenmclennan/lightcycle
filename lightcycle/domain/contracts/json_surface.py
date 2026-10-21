from lightcycle.domain.runs.pass_record import Pass
from lightcycle.domain.runs.phase_run import PhaseRun
from lightcycle.domain.work.item import Item
from lightcycle.domain.work.node_view import NodeView
from lightcycle.domain.work.step import Step


READ_SURFACE_EXTRA_KEYS = frozenset({
    "artifacts", "branch", "config", "description", "detail", "detail_presents",
    "guidance_delivered", "guidance_skipped", "inputs", "item_artifacts", "notes", "outputs",
    "passes", "phase", "pr", "records", "repo_path", "routes", "runs", "session_id", "skill",
    "spec_path", "valid_outcomes", "workflow", "workflow_error", "workflow_resolved",
    "workflow_source", "workspace",
})


def json_surface():
    keys = set(READ_SURFACE_EXTRA_KEYS)
    keys |= Item(id="x").as_dict().keys()
    step = Step(id="x", item="y")
    keys |= step.as_dict().keys()
    keys |= NodeView(step=step, item_artifacts=[]).as_dict().keys()
    keys |= PhaseRun(id="x", item="y", pass_id="z").as_dict().keys()
    keys |= Pass(id="x", item="y", n=1).as_dict().keys()
    return keys
