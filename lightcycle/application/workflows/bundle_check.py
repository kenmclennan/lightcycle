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
        unresolved = FlowContracts(flow, graph, step_metas).unresolved_steps()
        if unresolved:
            problems[name] = unresolved
    return problems
