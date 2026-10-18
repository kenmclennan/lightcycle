import re

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]")


def _safe(part):
    return _UNSAFE.sub("_", str(part))


def script_log_label(step_id):
    return "script-%s" % _safe(step_id)


def guard_log_label(schedule_id):
    return "guard-%s" % _safe(schedule_id)


def hook_log_label(origin, name, hook):
    return "hook-%s-%s-%s" % (_safe(origin), _safe(name), _safe(hook))

