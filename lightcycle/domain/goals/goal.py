from collections import namedtuple

GOAL_STATUSES = ("not started", "in progress", "done")
GOAL_DEFAULT_STATUS = "not started"

Goal = namedtuple(
    "Goal",
    "id title description project status created_at updated_at",
)
GoalLogEntry = namedtuple("GoalLogEntry", "id goal_id title body created_at")


def goal_log_stamp(value):
    return (value or "")[:16].replace("T", " ")
