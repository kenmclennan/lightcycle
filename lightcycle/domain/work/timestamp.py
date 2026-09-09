import datetime


def parse_timestamp(s):
    if not s:
        return None
    dt = datetime.datetime.fromisoformat(s)
    if dt.tzinfo is None:
        return dt.astimezone()
    return dt
