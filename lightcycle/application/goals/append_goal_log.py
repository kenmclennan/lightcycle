from lightcycle.application.errors import UseCaseError
from lightcycle.application.goals._common import require_goal, require_text


class AppendGoalLogUseCase:
    def __init__(self, store):
        self._store = store

    def execute(self, goal_id, title, body):
        require_goal(self._store, goal_id)
        title = require_text(title, "log entry title")
        if "\n" in title or "\r" in title:
            raise UseCaseError("log entry title must be a single line")
        self._store.add_goal_log(goal_id, title, require_text(body, "log entry"))


def log_entry_matches(entry, needle):
    if not needle:
        return True
    return needle.lower() in ("%s %s" % (entry.title, entry.body)).lower()
