from lightcycle.application.errors import UseCaseError
from lightcycle.domain.contracts import StepContract


def file_step(store, flow, item_id, node, workflow, project, step):
    graph = flow.load_graph(workflow, project)
    present = {a.type for a in store.item_artifacts(item_id)}
    missing_inputs = graph.requires - present
    if missing_inputs:
        raise UseCaseError(
            "item '%s' requires %s; attach them before activating"
            % (item_id, ", ".join(sorted(missing_inputs)))
        )
    step_name = step or graph.entry
    f = flow.load_flow(workflow, project)
    role = f.owner_of(step_name)
    if not role:
        raise UseCaseError(
            "step '%s' is not owned in workflow '%s'; owned steps: %s"
            % (step_name, workflow, ", ".join(f.steps()) or "(none)")
        )
    unmet = StepContract.from_meta(
        flow.meta_for_step(step_name, workflow, project)
    ).missing_inputs(present)
    if unmet:
        raise UseCaseError(
            "step '%s' requires %s; attach them before activating"
            % (step_name, ", ".join(sorted(unmet)))
        )
    return store.create_step(
        "%s: %s" % (step_name, node.title), step=step_name, role=role, parent=item_id
    )
