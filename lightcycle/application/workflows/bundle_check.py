from lightcycle.domain.contracts import FlowContracts
from lightcycle.domain.flow import Flow
from lightcycle.domain.flow.graph import parse_graph


def check_bundle_references(fs, root):
    step_metas = {
        role: (fs.parse_step(role, root) or {"meta": {}})["meta"]
        for role in fs.step_roles(root)
    }
    problems = {}
    for name in fs.workflow_names(root):
        graph = parse_graph(fs.workflow_text(name, root))
        flow = Flow.from_graph(graph, step_metas)
        contracts = FlowContracts(flow, graph, step_metas)
        messages = []
        if contracts.unresolved_steps():
            messages.append(
                "unresolved step reference(s): %s" % ", ".join(contracts.unresolved_steps())
            )
        if contracts.phase_gaps():
            messages.append("stages missing a phase: %s" % ", ".join(contracts.phase_gaps()))
        if contracts.unknown_phases():
            messages.append(
                "phase declared for unknown stage: %s" % ", ".join(contracts.unknown_phases())
            )
        for phase, workspaces in sorted(contracts.phase_conflicts().items()):
            messages.append("phase %r spans workspaces: %s" % (phase, ", ".join(workspaces)))
        if messages:
            problems[name] = messages
    return problems
