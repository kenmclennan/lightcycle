import datetime
import re

_NUMBER = re.compile(r"^\d+$")
_HORIZON_DAYS = 366 * 5
_VALIDATION_REFERENCE = datetime.datetime.fromisoformat("2024-01-01T00:00:00")

_FIELDS = (
    ("minute", 0, 59),
    ("hour", 0, 23),
    ("day-of-month", 1, 31),
    ("month", 1, 12),
    ("day-of-week", 0, 7),
)


class Cron:
    def __init__(self, minutes, hours, days, months, weekdays, days_any, weekdays_any):
        self.minutes = minutes
        self.hours = hours
        self.days = days
        self.months = months
        self.weekdays = weekdays
        self.days_any = days_any
        self.weekdays_any = weekdays_any

    def day_matches(self, day):
        in_month = day.day in self.days
        in_week = (day.isoweekday() % 7) in self.weekdays
        if self.days_any and self.weekdays_any:
            return True
        if self.days_any:
            return in_week
        if self.weekdays_any:
            return in_month
        return in_month or in_week


def _number(text, name, lo, hi):
    if not _NUMBER.match(text):
        raise ValueError("cron %s field: unsupported value %r" % (name, text))
    value = int(text)
    if value < lo or value > hi:
        raise ValueError("cron %s field: %d is outside %d-%d" % (name, value, lo, hi))
    return value


def _parse_part(part, name, lo, hi):
    base, slash, step_text = part.partition("/")
    step = 1
    if slash:
        if not _NUMBER.match(step_text) or int(step_text) < 1:
            raise ValueError("cron %s field: bad step %r" % (name, step_text))
        step = int(step_text)
    if base == "*":
        start, end = lo, hi
    elif "-" in base:
        left, _, right = base.partition("-")
        start = _number(left, name, lo, hi)
        end = _number(right, name, lo, hi)
        if start > end:
            raise ValueError("cron %s field: range %r runs backwards" % (name, base))
    else:
        if slash:
            raise ValueError("cron %s field: a step needs * or a range, got %r" % (name, base))
        value = _number(base, name, lo, hi)
        return {value}
    return set(range(start, end + 1, step))


def _parse_field(text, name, lo, hi):
    if not text:
        raise ValueError("cron %s field is empty" % name)
    values = set()
    for part in text.split(","):
        values |= _parse_part(part, name, lo, hi)
    return values


def parse_cron(expr):
    parts = str(expr).split()
    if len(parts) != 5:
        raise ValueError("cron expression %r needs exactly five fields" % (expr,))
    sets = [
        _parse_field(text, name, lo, hi)
        for text, (name, lo, hi) in zip(parts, _FIELDS)
    ]
    weekdays = {v % 7 for v in sets[4]}
    cron = Cron(
        sorted(sets[0]), sorted(sets[1]), set(sets[2]), set(sets[3]), weekdays,
        parts[2].startswith("*"), parts[4].startswith("*"),
    )
    if next_due(cron, _VALIDATION_REFERENCE) is None:
        raise ValueError("cron expression %r never matches" % (expr,))
    return cron


def _as_cron(expr):
    return expr if isinstance(expr, Cron) else parse_cron(expr)


def _floor(at):
    return at.replace(second=0, microsecond=0)


def next_due(expr, at):
    cron = _as_cron(expr)
    start = _floor(at) + datetime.timedelta(minutes=1)
    day = start.date()
    for offset in range(_HORIZON_DAYS):
        current = day + datetime.timedelta(days=offset)
        if current.month not in cron.months or not cron.day_matches(current):
            continue
        for hour in cron.hours:
            for minute in cron.minutes:
                candidate = datetime.datetime.combine(current, datetime.time(hour, minute))
                if candidate >= start:
                    return candidate
    return None


def previous_due(expr, at):
    cron = _as_cron(expr)
    stop = _floor(at)
    day = stop.date()
    for offset in range(_HORIZON_DAYS):
        current = day - datetime.timedelta(days=offset)
        if current.month not in cron.months or not cron.day_matches(current):
            continue
        for hour in reversed(cron.hours):
            for minute in reversed(cron.minutes):
                candidate = datetime.datetime.combine(current, datetime.time(hour, minute))
                if candidate <= stop:
                    return candidate
    return None
