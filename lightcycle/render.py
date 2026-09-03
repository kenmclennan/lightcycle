from lightcycle.domain.work import display_stage, park_resume_command
from lightcycle.domain.audit import StepKind


def node_extra(node, *, show_description=False, description=None, artifacts=None):
    pool = artifacts if artifacts else getattr(node, "artifacts", ())
    plan = next((a.value for a in pool if a.type == "plan-doc"), None)
    extra = "  plan:%s" % plan if plan else ""
    text = description if description is not None else getattr(node, "description", None)
    if show_description and text:
        extra += "  desc:%s" % _truncate(text)
    return extra


def _truncate(text, limit=60):
    return text[:limit] + ("..." if len(text) > limit else "")


def render_backlog(rows, title_cap):
    show_kind = len({r.kind for r in rows}) > 1
    return [_flat_line(r, show_kind, title_cap) for r in rows]


def _flat_line(r, show_kind, title_cap):
    title = _truncate(r.step.title or r.step.step, title_cap)
    project = r.project or "-"
    extra = node_extra(
        r.step, show_description=True,
        description=r.description, artifacts=r.artifacts,
    )
    if show_kind:
        return "[%s]  %-10s  %-12s  %s%s" % (r.kind, r.step.id, project, title, extra)
    return "%-10s  %-12s  %s%s" % (r.step.id, project, title, extra)


def render_inbox(rows, title_cap, flow_service=None):
    return [_inbox_line(r, title_cap, flow_service) for r in rows]


def _inbox_line(r, title_cap, flow_service=None):
    title = _truncate(r.step.title or r.step.step, title_cap)
    project = r.project or "-"
    line = "%-9s  %-10s  %-12s  %s" % ("[%s]" % r.kind, r.step.id, project, title)
    return (
        line + _strategy_suffix(r) + node_extra(
            r.step, show_description=True,
            description=r.description, artifacts=r.artifacts,
        )
        + _step_extra(r.step, flow_service)
    )


def _step_extra(node, flow_service):
    if flow_service is None or not node.step:
        return ""
    return "  step:%s" % display_stage(flow_service.display_for(node), node.step)


def render_search(matches, title_cap):
    return [_search_line(m, title_cap) for m in matches]


def _search_line(m, title_cap):
    title = _truncate(m.node.title or m.node.id, title_cap)
    project = m.project or "-"
    return "%-10s  %-8s  %-12s  %s  [%s] %s" % (
        m.node.id, m.node.state, project, title, m.field, m.snippet,
    )


def render_queue(steps, title_cap):
    return [
        "  %-8s %s  %s" % (t.state, t.id, _truncate(t.title, title_cap)) for t in steps
    ]


def _strategy_suffix(r):
    if r.kind == "blocked" and r.step.park.needs:
        parts = ["needs:%s" % r.step.park.needs]
        if r.step.park.reason:
            parts.append("reason:%s" % _truncate(r.step.park.reason))
        parts.append("resume:%s" % park_resume_command(r.step.id))
        return "  " + "  ".join(parts)
    if StepKind.of(r.step) is StepKind.ENGINE_FINDINGS and r.step.notes:
        return "  findings:%s" % _truncate(r.step.notes.splitlines()[0])
    if r.pr:
        return "  pr:%s" % r.pr
    return ""


def _mermaid_stages(graph):
    stages = set()
    if graph.entry:
        stages.add(graph.entry)
    stages.update(graph.nodes.keys())
    for frm, outs in graph.edges.items():
        stages.add(frm)
        stages.update(t for t in outs.values() if t)
    for occs in graph.hooks.values():
        for occ in occs:
            if occ:
                stages.add(occ[0])
    for occ in graph.hook_occurrences("pr_feedback"):
        if len(occ) > 1:
            stages.add(occ[1])
    for occ in graph.hook_occurrences("ci_failed_cap"):
        if len(occ) > 3:
            stages.add(occ[3])
    stages.update(graph.signals.keys())
    return stages


def _mermaid_node_id(stage):
    return stage.replace("-", "_")


def _mermaid_kind(owner):
    if owner == "human":
        return "human"
    if owner:
        return "agent"
    return "terminal"


def _mermaid_declare(stage, kind):
    sid = _mermaid_node_id(stage)
    if kind == "agent":
        return '%s["%s"]' % (sid, stage)
    if kind == "human":
        return '%s("%s")' % (sid, stage)
    return '%s(["%s"])' % (sid, stage)


def _mermaid_consumed_outcomes(graph, flow, stage):
    consumed = set()
    for outcome in (
        flow.merge_outcome(stage), flow.close_outcome(stage), flow.pr_conflict_outcome(stage)
    ):
        if outcome and graph.target(stage, outcome):
            consumed.add(outcome)
    return consumed


def _mermaid_hook_edges(graph, flow, stage):
    sid = _mermaid_node_id(stage)
    edges = []
    merge_o = flow.merge_outcome(stage)
    if merge_o:
        target = graph.target(stage, merge_o)
        if target:
            edges.append("%s -.->|pr_merge: %s| %s" % (sid, merge_o, _mermaid_node_id(target)))
    close_o = flow.close_outcome(stage)
    if close_o:
        target = graph.target(stage, close_o)
        if target:
            edges.append("%s -.->|pr_close: %s| %s" % (sid, close_o, _mermaid_node_id(target)))
    conflict_o = flow.pr_conflict_outcome(stage)
    if conflict_o:
        target = graph.target(stage, conflict_o)
        if target:
            edges.append(
                "%s -.->|pr_conflict: %s| %s" % (sid, conflict_o, _mermaid_node_id(target))
            )
    cap = flow.pr_conflict_cap(stage)
    escalate = flow.pr_conflict_escalate(stage)
    if cap and escalate:
        target = graph.target(stage, escalate)
        if target:
            edges.append(
                "%s -.->|pr_conflict_cap x%d: %s| %s"
                % (sid, cap, escalate, _mermaid_node_id(target))
            )
    feedback = flow.pr_feedback_step(stage)
    if feedback:
        edges.append("%s -.->|pr_feedback| %s" % (sid, _mermaid_node_id(feedback)))
    ci_target = flow.ci_failed_cap_target(stage)
    if ci_target:
        edges.append(
            "%s -.->|ci_failed_cap x%d: %s| %s"
            % (sid, flow.ci_failed_cap_n(stage), flow.ci_failed_cap_outcome(stage),
               _mermaid_node_id(ci_target))
        )
    return edges


def render_workflow_mermaid(graph, flow):
    stages = _mermaid_stages(graph)
    kinds = {stage: _mermaid_kind(flow.owner_of(stage)) for stage in stages}

    lines = ["flowchart TD"]

    phased = sorted(s for s in stages if graph.phases.get(s))
    unphased = sorted(s for s in stages if not graph.phases.get(s))
    if phased:
        by_phase = {}
        for s in phased:
            by_phase.setdefault(graph.phases[s], []).append(s)
        for phase in sorted(by_phase):
            lines.append('subgraph phase_%s["%s"]' % (phase, phase))
            for s in sorted(by_phase[phase]):
                lines.append("  " + _mermaid_declare(s, kinds[s]))
            lines.append("end")
    for s in unphased:
        lines.append(_mermaid_declare(s, kinds[s]))

    lines.append("classDef agent fill:#e8f0fe,stroke:#4285f4,color:#202124")
    lines.append("classDef human fill:#fef7e0,stroke:#f9ab00,color:#202124")
    lines.append("classDef terminal fill:#f1f3f4,stroke:#5f6368,color:#202124,stroke-dasharray: 3 3")
    for kind in ("agent", "human", "terminal"):
        ids = sorted(_mermaid_node_id(s) for s in stages if kinds[s] == kind)
        if ids:
            lines.append("class %s %s" % (",".join(ids), kind))

    consumed = {stage: _mermaid_consumed_outcomes(graph, flow, stage) for stage in graph.edges}
    for frm in sorted(graph.edges):
        for outcome in sorted(graph.edges[frm]):
            if outcome in consumed.get(frm, set()):
                continue
            target = graph.edges[frm][outcome]
            if not target:
                continue
            lines.append("%s -->|%s| %s" % (_mermaid_node_id(frm), outcome, _mermaid_node_id(target)))

    for stage in sorted(stages):
        lines.extend(_mermaid_hook_edges(graph, flow, stage))

    return lines
