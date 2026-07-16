def node_extra(node, *, show_description=False):
    plan = next((a.value for a in node.artifacts if a.type == "plan-doc"), None)
    extra = "  plan:%s" % plan if plan else ""
    if show_description and node.description:
        snippet = node.description[:60] + ("..." if len(node.description) > 60 else "")
        extra += "  desc:%s" % snippet
    return extra


def render_backlog(rows):
    show_kind = len({r.kind for r in rows}) > 1
    return [_flat_line(r, show_kind) for r in rows]


def render_backlog_themed(groups):
    lines = []
    for i, g in enumerate(groups):
        if i:
            lines.append("")
        show_kind = len({r.kind for r in g.rows}) > 1
        if g.theme is None:
            lines.append("(no theme)")
            lines.extend(_flat_line(r, show_kind) for r in g.rows)
        else:
            lines.append("%s  %s  %s" % (g.theme.id, g.project or "-", g.theme.title))
            lines.extend("    " + _item_line(r, show_kind) for r in g.rows)
    return lines


def _flat_line(r, show_kind):
    title = r.step.title or r.step.step
    project = r.project or "-"
    extra = node_extra(r.step, show_description=True)
    if show_kind:
        return "[%s]  %-10s  %-12s  %s%s" % (r.kind, r.step.id, project, title, extra)
    return "%-10s  %-12s  %s%s" % (r.step.id, project, title, extra)


def _item_line(r, show_kind):
    title = r.step.title or r.step.step
    extra = node_extra(r.step, show_description=True)
    if show_kind:
        return "[%s]  %s  %s%s" % (r.kind, r.step.id, title, extra)
    return "%s  %s%s" % (r.step.id, title, extra)
