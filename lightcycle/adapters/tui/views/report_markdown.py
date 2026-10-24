import re

from lightcycle.adapters.tui.hub_render import _format_item_cost
from lightcycle.domain.work.summary_split import _BRACKET_AT_END


def _plural(count, singular, plural):
    return "%d %s" % (count, singular if count == 1 else plural)


def _title(day):
    return "# %s %d %s %d" % (day.strftime("%A"), day.day, day.strftime("%B"), day.year)


def _top_line(response):
    delta = response.backlog_delta
    delta_text = "+%d" % delta if delta >= 0 else str(delta)
    closed = response.completed + response.abandoned
    return " · ".join((
        _plural(closed, "item closed", "items closed"),
        "%s spent" % _format_item_cost(response.spend),
        "%s (%s)" % (
            _plural(response.automation_count, "automation item", "automation items"),
            _format_item_cost(response.automation_spend),
        ),
        _plural(response.escalations, "escalation", "escalations"),
        "backlog %d → %d (%s)" % (response.backlog_start, response.backlog_close, delta_text),
    ))


def _parenthesise_ids(bullet):
    match = _BRACKET_AT_END.search(bullet)
    if match is None:
        return bullet
    ids = [part for part in re.split(r"[,\s]+", match.group(1)) if part]
    tail = bullet[match.end(1) + 1:]
    return bullet[:match.start()] + "(" + ", ".join(ids) + ")" + tail


def _project_section(project):
    closed = project.completed + project.abandoned
    name = project.project if project.project is not None else "No project"
    blocks = [
        "## %s" % name,
        "%d closed · %s · %d escalations" % (closed, _format_item_cost(project.spend), project.escalations),
    ]
    for label, bullets in (
        ("Delivered", project.delivered), ("Fixed", project.fixed), ("Improved", project.improved),
    ):
        if bullets:
            blocks.append("### %s" % label)
            blocks.append("\n".join(_parenthesise_ids(bullet) for bullet in bullets))
    return blocks


def report_markdown(response):
    blocks = [_title(response.day), _top_line(response)]
    for project in response.projects:
        blocks.extend(_project_section(project))
    if response.summary_unmatched:
        blocks.append("## Not matched to a project")
        blocks.append(response.summary_unmatched)
    return "\n\n".join(blocks) + "\n"
