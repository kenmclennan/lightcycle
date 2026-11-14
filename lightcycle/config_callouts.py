import re
from dataclasses import dataclass

from lightcycle.config_ranges import parse_bool
from lightcycle.domain.work.step_focus import parse_presents

CALLOUT_KEY_PREFIX = "callout-"
CALLOUT_KEYS = ("command", "subject", "wait", "timeout")
_ID = re.compile(r"^[a-z0-9-]+$")


@dataclass(frozen=True)
class Callout:
    id: str
    command: str
    subject: str
    wait: bool
    timeout: int


def callout_blocks(values):
    return {
        k[len(CALLOUT_KEY_PREFIX):]: dict(v)
        for k, v in values.items()
        if k.startswith(CALLOUT_KEY_PREFIX) and isinstance(v, dict)
    }


def _blank(value):
    return value is None or not str(value).strip()


def _timeout_problem(raw):
    try:
        seconds = int(str(raw).strip())
    except ValueError:
        return "key 'timeout' must be whole seconds (got %r)" % raw
    if seconds < 1:
        return "key 'timeout' must be at least 1 second (got %r)" % raw
    return None


def callout_problems(block, callout_id):
    problems = []
    if not _ID.match(callout_id or ""):
        problems.append("callout id %r must match [a-z0-9-]+" % callout_id)
    for key in block:
        if key not in CALLOUT_KEYS:
            problems.append("unknown key %r" % key)
    for key in CALLOUT_KEYS:
        if _blank(block.get(key)):
            problems.append("key %r is missing or blank" % key)
    subject = block.get("subject")
    if not _blank(subject) and parse_presents(subject) is None:
        problems.append(
            "key 'subject' must be pr, description or artifact:<name> (got %r)" % subject)
    wait = block.get("wait")
    if not _blank(wait):
        try:
            parse_bool("wait", wait)
        except ValueError:
            problems.append("key 'wait' must be true or false (got %r)" % wait)
    timeout = block.get("timeout")
    if not _blank(timeout):
        problem = _timeout_problem(timeout)
        if problem:
            problems.append(problem)
    return problems


def valid_callouts(blocks, expand_path):
    callouts = []
    for callout_id, block in blocks.items():
        if callout_problems(block, callout_id):
            continue
        callouts.append(Callout(
            id=callout_id,
            command=expand_path(str(block["command"]).strip()),
            subject=str(block["subject"]).strip(),
            wait=parse_bool("wait", block["wait"]),
            timeout=int(str(block["timeout"]).strip()),
        ))
    return callouts
