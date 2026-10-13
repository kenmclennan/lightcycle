def node_read_surface(store, flow, view):
    step = view.step
    item_id = getattr(step, "item", None) or step.id
    out = view.as_dict()
    if step.type == "step":
        step_artifacts = store.item_artifacts(step.id)
        out["artifacts"] = [a.as_dict() for a in step_artifacts]
        artifacts = {a.type: a.value for a in step_artifacts}
        if artifacts.get("session-id"):
            out["session_id"] = artifacts["session-id"]
        for artifact_type, field in (
            ("guidance-delivered", "guidance_delivered"),
            ("guidance-skipped", "guidance_skipped"),
        ):
            if artifact_type in artifacts:
                out[field] = [i for i in artifacts[artifact_type].split("\n") if i]
    out["workflow"] = store.get_item(item_id).workflow
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
    if out["workflow_resolved"]:
        phase = flow.phase_for(step)
        if phase:
            out["phase"] = phase
            run = store.current_run(item_id, phase)
            if run and run.pr:
                out["pr"] = run.pr
    return out
