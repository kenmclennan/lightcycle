from lightcycle.domain.flow.flow import PROJECT_WORKSPACE


def stack_run_of(runs, workspace_of_phase):
    for run in sorted(runs, key=lambda r: r.opened_at or "", reverse=True):
        if run.branch and workspace_of_phase(run.phase) == PROJECT_WORKSPACE:
            return run
    return None


def has_stack_phase(graph):
    if not graph.phases:
        return graph.workspace == PROJECT_WORKSPACE
    return any(graph.workspace_for(stage) == PROJECT_WORKSPACE for stage in graph.phases)
