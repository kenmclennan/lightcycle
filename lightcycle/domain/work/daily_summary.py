from collections import namedtuple

DailySummary = namedtuple(
    "DailySummary",
    "day summary generated_at summarized_count dirty_since step_id spawn_count",
)
