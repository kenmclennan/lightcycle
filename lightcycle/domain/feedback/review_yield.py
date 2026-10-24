import json
from dataclasses import dataclass
from typing import Optional

SOURCE_TRUSTED = "trusted"
SOURCE_BOT = "bot"
SOURCE_OTHER = "other"
SOURCE_MIXED = "mixed"
SOURCE_UNKNOWN = "unknown"

VIA_CHANGE_REQUEST = "change-request"
VIA_PR_COMMENT = "pr-comment"

REVIEW_FINDINGS = "review-findings"
CAUSED_BY = "caused-by"
FOUND_BY = "found-by"

FINDING_KEYS = ("severity", "kind", "file", "line", "summary")
FOUND_BY_MAX = 40
BOT_SUFFIX = "[bot]"


@dataclass(frozen=True)
class ReviewEscape:
    trigger_step: str
    item: str
    run_id: str
    verdict_step: str
    via: str
    at: str
    note: Optional[str]
    source: str
    authors: Optional[str]


def _login_class(login, trusted):
    folded = login.casefold()
    if folded.endswith(BOT_SUFFIX):
        return SOURCE_BOT
    if folded in trusted:
        return SOURCE_TRUSTED
    return SOURCE_OTHER


def classify_source(authors, trusted):
    logins = sorted({a for a in authors if a})
    if not logins:
        return SOURCE_UNKNOWN
    classes = {_login_class(a, trusted) for a in logins}
    return classes.pop() if len(classes) == 1 else SOURCE_MIXED


def authors_text(authors):
    logins = sorted({a for a in authors if a})
    return ",".join(logins) if logins else None


def latest_passing_verdict(candidates):
    best = None
    for step in candidates:
        if best is None or (step.closed_at or "", step.id) > (best.closed_at or "", best.id):
            best = step
    return best


def parse_findings(text):
    try:
        data = json.loads(text)
    except ValueError as e:
        raise ValueError("review-findings is not valid JSON: %s" % e)
    if not isinstance(data, list):
        raise ValueError("review-findings must be a JSON array")
    for index, element in enumerate(data):
        problem = _finding_problem(element)
        if problem:
            raise ValueError("review-findings[%d] %s" % (index, problem))
    return data


def _finding_problem(element):
    if not isinstance(element, dict):
        return "must be an object"
    keys = set(element)
    missing = [k for k in FINDING_KEYS if k not in keys]
    extra = sorted(keys - set(FINDING_KEYS))
    if missing:
        return "is missing %s" % ", ".join(missing)
    if extra:
        return "has unknown key(s) %s" % ", ".join(extra)
    for key in ("severity", "kind", "summary"):
        value = element[key]
        if not isinstance(value, str) or not value.strip():
            return "%s must be a non-empty string" % key
    if "\n" in element["summary"] or "\r" in element["summary"]:
        return "summary must be a single line"
    file, line = element["file"], element["line"]
    if file is not None and not isinstance(file, str):
        return "file must be a string or null"
    if line is not None and (isinstance(line, bool) or not isinstance(line, int) or line < 1):
        return "line must be a positive integer or null"
    if file is None and line is not None:
        return "line must be null when file is null"
    return None


def found_by_problem(token):
    if not token or any(ch.isspace() for ch in token):
        return "found-by must be a non-empty token without whitespace"
    if len(token) > FOUND_BY_MAX:
        return "found-by must be at most %d characters" % FOUND_BY_MAX
    return None
