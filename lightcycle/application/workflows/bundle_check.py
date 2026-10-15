from lightcycle import frontmatter
from lightcycle.application.workflows.prompt_check import check_prompt_commands
from lightcycle.domain.contracts import FlowContracts
from lightcycle.domain.flow import Flow
from lightcycle.domain.flow.graph import parse_graph
from lightcycle.domain.workflows.step_structure import check_step_structure


def _step_texts(bundle):
    texts = {}
    for role, text in bundle.steps.items():
        _, body = frontmatter.split_frontmatter(text)
        if not body:
            continue
        if body != text:
            body = "\n" * (len(text.splitlines()) - len(body.split("\n"))) + body
        texts["steps/%s.md" % role] = body
    return texts


def check_prompts(bundle, cli_surface, json_keys):
    return check_prompt_commands(_step_texts(bundle), cli_surface, json_keys)


def check_step_structure_for(bundle, fragment_names):
    return check_step_structure(
        _step_texts(bundle), set(fragment_names) | set(bundle.fragments))


def merge_problems(*problem_maps):
    merged = {}
    for problems in problem_maps:
        for step, messages in problems.items():
            merged.setdefault(step, []).extend(messages)
    return merged


def undeclared_target_message(frm, outcome, target):
    message = "edge '%s %s %s' targets '%s', which is not a declared stage" % (
        frm, outcome, target, target)
    if target == "primary":
        message += (
            "; 'primary' belongs in the fourth column, and a terminal edge has no target")
    return message


def check_bundle_references(bundle):
    step_metas = {}
    for role, text in bundle.steps.items():
        meta, _ = frontmatter.split_frontmatter(text)
        step_metas[role] = meta
    problems = {}
    for name, text in bundle.workflows.items():
        try:
            graph = parse_graph(text)
        except ValueError as e:
            problems[name] = ["parse error: %s" % e]
            continue
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
        for hook, gate, got, want in contracts.malformed_hook_occurrences():
            messages.append(
                "%s on %r has %d token(s), needs at least %d" % (hook, gate, got, want)
            )
        for frm, outcome, target in contracts.undeclared_edge_targets():
            messages.append(undeclared_target_message(frm, outcome, target))
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
