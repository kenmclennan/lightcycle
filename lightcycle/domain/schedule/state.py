import re

SCHEDULE_STATE_ARTIFACT = "schedule-state"

_DAY_STATE = re.compile(r"^day: (\d{4}-\d{2}-\d{2}) count: (\d+)$")
_BATCH_PREFIX = "batch: "


def parse_day_state(value):
    match = _DAY_STATE.match(value or "")
    if not match:
        return None
    return match.group(1), int(match.group(2))


def parse_batch_state(value):
    if not (value or "").startswith(_BATCH_PREFIX):
        return None
    return tuple(i.strip() for i in value[len(_BATCH_PREFIX):].split(",") if i.strip())
