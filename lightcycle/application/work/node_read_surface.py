from lightcycle.application.flow.engine_steps import engine_outcomes_for_node
from lightcycle.application.work.item_outputs import ItemOutputs
from lightcycle.application.work.step_detail import StepDetail
from lightcycle.application.work.step_inputs import StepInputs
from lightcycle.domain.work.forwarded_note import shim_notes


def node_read_surface(store, flow, view):
    step = view.step
    item_id = getattr(step, "item", None) or step.id
    out = view.as_dict()
    if step.type == "step":
        step_artifacts = store.item_artifacts(step.id)
        out["artifacts"] = [a.as_dict() for a in step_artifacts]
        item_outputs = ItemOutputs(store, flow)
        out["item_artifacts"] = [
            a.as_dict() for a in item_outputs.reader_artifacts(step, item_outputs.for_reader(step))
        ]
        step_inputs = StepInputs(store, flow)
        inputs = step_inputs.read(step)
        output_entries = step_inputs.entry_dicts_for_step(step)
        _produced, records = item_outputs.step_rows(step)
        out["inputs"] = inputs
        out["outputs"] = {"report": step.report, "artifacts": output_entries}
        out["records"] = [
            {"type": r.type, "label": r.label, "value": r.value} for r in records
        ]
        entries, presents = StepDetail(store, flow).resolve(step, inputs, output_entries)
        out["detail"] = [e.as_dict() for e in entries]
        out["detail_presents"] = presents
        prev = step_inputs.previous(step)
        if prev is not None:
            out["notes"] = shim_notes(prev.stage, prev.outcome, prev.report, step.notes)
        artifacts = {a.type: a.value for a in step_artifacts}
        if artifacts.get("session-id"):
            out["session_id"] = artifacts["session-id"]
        for artifact_type, field in (
            ("guidance-delivered", "guidance_delivered"),
            ("guidance-skipped", "guidance_skipped"),
        ):
            if artifact_type in artifacts:
                out[field] = [i for i in artifacts[artifact_type].split("\n") if i]
    if step.type == "item":
        out["outputs"] = {"artifacts": ItemOutputs(store, flow).for_item(step.id).entry_dicts()}
    out["workflow"] = store.item_workflow(item_id)
    out["passes"] = [p.as_dict() for p in store.passes_of(item_id)]
    out["runs"] = [r.as_dict() for r in store.runs_of(item_id)]
    skill = flow.step_skill(step)
    if skill:
        out["skill"] = skill
    selector, source = flow.workflow_owner(step)
    out["workflow_resolved"] = None
    out["workflow_source"] = source
    out["workflow_error"] = None
    if selector is not None:
        try:
            pin = flow.resolve_selection(selector)
            flow.load_graph(pin)
        except ValueError as e:
            out["workflow_error"] = str(e)
        else:
            out["workflow_resolved"] = pin
    if step.type == "step":
        engine_valid = engine_outcomes_for_node(store, step)
        if engine_valid is not None:
            out["valid_outcomes"] = list(engine_valid)
            out["routes"] = {}
        elif out["workflow_resolved"]:
            out["valid_outcomes"] = flow.outcomes_for(step.stage, out["workflow_resolved"])
            out["routes"] = flow.routes_for(step.stage, out["workflow_resolved"])
        else:
            out["valid_outcomes"] = []
            out["routes"] = {}
    if out["workflow_resolved"]:
        phase = flow.phase_for(step)
        if phase:
            out["phase"] = phase
            run = store.current_run(item_id, phase)
            if run and run.pr:
                out["pr"] = run.pr
    return out
