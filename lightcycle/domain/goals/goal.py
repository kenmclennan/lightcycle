from collections import namedtuple

GOAL_STATUSES = ("not started", "in progress", "done")
GOAL_DEFAULT_STATUS = "not started"

Goal = namedtuple("Goal", "id title description project status created_at updated_at")
GoalLogEntry = namedtuple("GoalLogEntry", "id goal_id body created_at")
