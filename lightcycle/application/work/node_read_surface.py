from lightcycle.application.flow.engine_steps import engine_outcomes_for_node
from lightcycle.application.work.step_detail import StepDetail
from lightcycle.application.work.stack_runs import StackRuns
from lightcycle.application.work.step_inputs import StepInputs
from lightcycle.domain.flow.flow import PROJECT_WORKSPACE
from lightcycle.domain.runs import RunState
from lightcycle.domain.work import State
from lightcycle.domain.work.forwarded_note import shim_notes
from lightcycle.ports.store import NodeNotFoundError


def _slice_runs(store, item_id, pass_id=None):
    if pass_id is None:
        current = store.current_pass(item_id)
        if current is None:
            return []
        pass_id = current.id
    latest = {}
    for run in store.runs_of(item_id, pass_id):
        if run.slice > 0:
            latest.setdefault(run.slice, []).append(run)
    return [runs[0] for _, runs in sorted(latest.items())]


def _slices_of(store, item_id):
    current = store.current_pass(item_id)
    rows = []
    for run in _slice_runs(store, item_id):
        open_step = next(
            (c.id for c in store.children(item_id)
             if c.slice == run.slice and c.state != State.DONE
             and c.pass_id == current.id),
            None,
        )
        rows.append({
            "slice": run.slice, "name": run.slice_name, "base": run.base_slice,
            "state": run.state, "branch": run.branch, "pr": run.pr, "step": open_step,
        })
    return rows


def _slice_stack_of(store, step, item_id):
    current = store.current_pass(item_id)
    if current is None:
        return False
    runs = store.runs_of(item_id, current.id)
    own = next((r for r in runs if r.slice == step.slice), None)
    if own is None or own.base_slice is None:
        return False
    base_runs = [r for r in runs if r.phase == own.phase and r.slice == own.base_slice]
    base = base_runs[-1] if base_runs else None
    if base is None or base.state != RunState.OPEN or not base.branch:
        return None
    item = store.item_fields(item_id)
    return {
        "parent": item_id,
        "parent_title": "%s - slice %s" % (item.title, base.slice_name),
        "branch": base.branch,
        "pr": base.pr,
    }


def _stack_of(store, flow, step, item_id):
    if getattr(step, "slice", 0) > 0:
        sliced = _slice_stack_of(store, step, item_id)
        if sliced is not False:
            return sliced
    parent_id = store.item_fields(item_id).stacks_on
    if not parent_id:
        return None
    if (flow.workspace_for_node(step) or PROJECT_WORKSPACE) != PROJECT_WORKSPACE:
        return None
    try:
        parent = store.item_fields(parent_id)
    except NodeNotFoundError:
        return None
    run = StackRuns(store, flow).run_of(parent_id)
    if run is None:
        return None
    return {
        "parent": parent_id,
        "parent_title": parent.title,
        "branch": run.branch,
        "pr": run.pr,
    }


def _slice_name(store, step, item_id):
    if step.slice <= 0:
        return None
    current = store.current_pass(item_id)
    if current is None:
        return None
    return next(
        (r.slice_name for r in store.runs_of(item_id, current.id) if r.slice == step.slice),
        None,
    )


def node_read_surface(store, flow, view, outputs):
    step = view.step
    item_id = getattr(step, "item", None) or step.id
    out = view.as_dict()
    if step.type == "step":
        step_artifacts = store.item_artifacts(step.id)
        out["artifacts"] = [a.as_dict() for a in step_artifacts]
        item_outputs = outputs
        out["item_artifacts"] = [
            a.as_dict() for a in item_outputs.reader_artifacts(step, item_outputs.for_reader(step))
        ]
        step_inputs = StepInputs(store, flow, outputs)
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
        out["stack"] = _stack_of(store, flow, step, item_id)
        out["slice_name"] = _slice_name(store, step, item_id)
        prev = step_inputs.previous(step)
        if prev is not None and prev.outcome:
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
        out["outputs"] = {"artifacts": outputs.for_item(step.id).entry_dicts()}
        out["stacked_children"] = [i.id for i in store.items_stacked_on(step.id)]
        out["slices"] = _slices_of(store, step.id)
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
            run = store.current_run(item_id, phase, getattr(step, "slice", 0))
            if run and run.pr:
                out["pr"] = run.pr
    return out
