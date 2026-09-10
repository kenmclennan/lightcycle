from lightcycle import frontmatter
from lightcycle.application.workflows.prompt_check import check_prompt_commands
from lightcycle.domain.contracts import FlowContracts
from lightcycle.domain.flow import Flow
from lightcycle.domain.flow.graph import parse_graph


def check_prompts(bundle, cli_source, domain_sources, flat_sources=None):
    texts = {}
    for role, text in bundle.steps.items():
        _, body = frontmatter.split_frontmatter(text)
        if body:
            texts["steps/%s.md" % role] = body
    return check_prompt_commands(texts, cli_source, domain_sources, flat_sources)


def check_bundle_references(bundle):
    step_metas = {}
    for role, text in bundle.steps.items():
        meta, _ = frontmatter.split_frontmatter(text)
        step_metas[role] = meta
    problems = {}
    for name, text in bundle.workflows.items():
        graph = parse_graph(text)
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
                "phase declared for a non-owned stage (only owned stages carry a phase; "
                "fileless terminals do not): %s" % ", ".join(contracts.unknown_phases())
            )
        for phase, workspaces in sorted(contracts.phase_conflicts().items()):
            messages.append("phase %r spans workspaces: %s" % (phase, ", ".join(workspaces)))
        for hook, gate, gate_phase, target, target_phase in contracts.hook_phase_mismatches():
            messages.append(
                "%s on %r (phase %r) targets %r in a different phase (%r)"
                % (hook, gate, gate_phase, target, target_phase)
            )
        for hook, gate, target in contracts.unresolved_hook_targets():
            messages.append(
                "%s on %r targets %r, which resolves to nothing" % (hook, gate, target)
            )
        if contracts.unknown_display():
            messages.append(
                "display phrase declared for a stage this bundle does not reference: %s"
                % ", ".join(contracts.unknown_display())
            )
        if contracts.unknown_pass_ends():
            messages.append(
                "pass-end declared for a stage this bundle does not reference: %s"
                % ", ".join(contracts.unknown_pass_ends())
            )
        if contracts.unreachable_pass_ends():
            messages.append(
                "pass-end names an outcome the stage cannot emit (no such edge): %s"
                % ", ".join(contracts.unreachable_pass_ends())
            )
        if messages:
            problems[name] = messages
    return problems
