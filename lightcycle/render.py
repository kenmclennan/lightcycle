def node_extra(node, *, show_description=False):
    plan = next((a.value for a in node.artifacts if a.type == "plan-doc"), None)
    extra = "  plan:%s" % plan if plan else ""
    if show_description and node.description:
        extra += "  desc:%s" % _truncate(node.description)
    return extra


def _truncate(text, limit=60):
    return text[:limit] + ("..." if len(text) > limit else "")


def render_backlog(rows, title_cap):
    show_kind = len({r.kind for r in rows}) > 1
    return [_flat_line(r, show_kind, title_cap) for r in rows]


def render_backlog_themed(groups, title_cap):
    lines = []
    for i, g in enumerate(groups):
        if i:
            lines.append("")
        show_kind = len({r.kind for r in g.rows}) > 1
        if g.theme is None:
            lines.append("(no theme)")
            lines.extend(_flat_line(r, show_kind, title_cap) for r in g.rows)
        else:
            lines.append("%s  %s  %s" % (g.theme.id, g.project or "-", g.theme.title))
            lines.extend("    " + _item_line(r, show_kind, title_cap) for r in g.rows)
    return lines


def _flat_line(r, show_kind, title_cap):
    title = _truncate(r.step.title or r.step.step, title_cap)
    project = r.project or "-"
    extra = node_extra(r.step, show_description=True)
    if show_kind:
        return "[%s]  %-10s  %-12s  %s%s" % (r.kind, r.step.id, project, title, extra)
    return "%-10s  %-12s  %s%s" % (r.step.id, project, title, extra)


def _item_line(r, show_kind, title_cap):
    title = _truncate(r.step.title or r.step.step, title_cap)
    extra = node_extra(r.step, show_description=True)
    if show_kind:
        return "[%s]  %s  %s%s" % (r.kind, r.step.id, title, extra)
    return "%s  %s%s" % (r.step.id, title, extra)


def render_inbox(rows, title_cap):
    return [_inbox_line(r, title_cap) for r in rows]


def _inbox_line(r, title_cap):
    title = _truncate(r.step.title or r.step.step, title_cap)
    project = r.project or "-"
    line = "%-9s  %-10s  %-12s  %s" % ("[%s]" % r.kind, r.step.id, project, title)
    return line + _strategy_suffix(r) + node_extra(r.step, show_description=True)


def render_queue(steps, title_cap):
    return [
        "  %-8s %s  %s" % (t.state, t.id, _truncate(t.title, title_cap)) for t in steps
    ]


def _strategy_suffix(r):
    if r.kind == "blocked" and r.step.needs:
        return "  needs:%s" % r.step.needs
    if r.kind == "triage" and r.step.notes:
        return "  findings:%s" % _truncate(r.step.notes.splitlines()[0])
    if r.pr:
        return "  pr:%s" % r.pr
    return ""
