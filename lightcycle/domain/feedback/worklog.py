import datetime


class Worklog:
    def __init__(self, items):
        self._stories = items

    def entries(self, period, tz):
        result = []
        for s in self._stories:
            closed_at = s.get("closed_at")
            if not closed_at:
                continue
            if not period.contains(self._closed_date(closed_at, tz)):
                continue
            pr = next((a.value for a in (s.get("artifacts") or []) if a.type == "pr"), None)
            result.append(
                {
                    "id": s["id"],
                    "title": s.get("title", ""),
                    "outcome": s.get("outcome"),
                    "pr": pr,
                }
            )
        return result

    @staticmethod
    def _closed_date(closed_at, tz):
        dt = datetime.datetime.fromisoformat(closed_at.replace("Z", "+00:00"))
        return dt.astimezone(tz).date()
