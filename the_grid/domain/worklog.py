"""Pure worklog logic: period resolution and story filter/shape."""
import datetime


def resolve_period(args, today):
    """Resolve positional date args to an inclusive (start, end) date range.

    today must be a datetime.date. Each arg is 'today', 'yesterday', or
    'YYYY-MM-DD'. No args -> today for both bounds.
    """
    def _parse(arg):
        if arg == "today":
            return today
        if arg == "yesterday":
            return today - datetime.timedelta(days=1)
        return datetime.date.fromisoformat(arg)

    if not args:
        return (today, today)
    if len(args) == 1:
        d = _parse(args[0])
        return (d, d)
    return (_parse(args[0]), _parse(args[1]))


def _closed_date(closed_at):
    dt = datetime.datetime.fromisoformat(closed_at.replace("Z", "+00:00"))
    return dt.astimezone().date()


def worklog(stories, start, end):
    """Stories closed within [start, end] inclusive, shaped for output.

    Each entry: {id, title, outcome, pr}. pr is None when no pr artifact.
    """
    result = []
    for s in stories:
        closed_at = s.get("closed_at")
        if not closed_at:
            continue
        if not (start <= _closed_date(closed_at) <= end):
            continue
        pr = next((a["value"] for a in (s.get("artifacts") or [])
                   if a.get("type") == "pr"), None)
        result.append({
            "id": s["id"],
            "title": s.get("title", ""),
            "outcome": s.get("outcome"),
            "pr": pr,
        })
    return result
