import json
from dataclasses import dataclass, field
from typing import Dict, Optional

from lightcycle.domain.workflows.lifecycle import SCRIPTS_PREFIX, script_path_shape_problem

FIXTURES_DIR = "fixtures"
TESTS_DIR = "tests"
STAGE_KEYS = ("outcome", "artifacts", "note")
GUARD_KEYS = ("outcome", "title", "description", "state", "note")
GUARD_PASS = "pass"
GUARD_FAIL = "fail"
GUARD_OUTCOMES = (GUARD_PASS, GUARD_FAIL)


@dataclass(frozen=True)
class StageOutput:
    outcome: str
    artifacts: Dict[str, str] = field(default_factory=dict)
    note: Optional[str] = None


@dataclass(frozen=True)
class GuardOutput:
    passed: bool
    title: str = ""
    description: str = ""
    state: str = ""
    note: str = ""


def parse_script_stage(step_meta):
    value = (step_meta or {}).get("script")
    if value is None:
        return None
    return str(value).strip() or None


def script_path_problem(label, path):
    return script_path_shape_problem(label, path)


def fixture_path(script_path):
    return "%s%s/%s.json" % (SCRIPTS_PREFIX, FIXTURES_DIR, script_path[len(SCRIPTS_PREFIX):])


def is_support_file(rel):
    first = rel.split("/", 1)[0]
    return first in (FIXTURES_DIR, TESTS_DIR)


def _load_object(text):
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        raise ValueError("output is not one JSON object")
    if not isinstance(data, dict):
        raise ValueError("output is not one JSON object")
    return data


def _unknown_keys(data, allowed):
    unknown = sorted(set(data) - set(allowed))
    if unknown:
        raise ValueError("output has unknown key(s) %s" % ", ".join(unknown))


def _optional_text(data, key):
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("output key %s must be a string" % key)
    return value


def parse_stage_output(text, outcomes):
    data = _load_object(text)
    _unknown_keys(data, STAGE_KEYS)
    outcome = data.get("outcome")
    if outcome is None:
        raise ValueError("output has no outcome")
    if not isinstance(outcome, str) or outcome not in outcomes:
        raise ValueError(
            "outcome %r is not declared for this stage (declared: %s)"
            % (outcome, ", ".join(sorted(outcomes))))
    artifacts = data.get("artifacts", {})
    if not isinstance(artifacts, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in artifacts.items()):
        raise ValueError("output key artifacts must map artifact types to strings")
    return StageOutput(outcome=outcome, artifacts=dict(artifacts), note=_optional_text(data, "note"))


def parse_guard_output(text):
    data = _load_object(text)
    _unknown_keys(data, GUARD_KEYS)
    outcome = data.get("outcome")
    if outcome not in GUARD_OUTCOMES:
        raise ValueError("guard outcome must be pass or fail (got %r)" % (outcome,))
    title = _optional_text(data, "title") or ""
    if outcome == GUARD_PASS and not title.strip():
        raise ValueError("a passing guard must return a title")
    return GuardOutput(
        passed=outcome == GUARD_PASS, title=title,
        description=_optional_text(data, "description") or "",
        state=_optional_text(data, "state") or "",
        note=_optional_text(data, "note") or "")


def parse_fixture(text, outcomes, guard=False):
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        raise ValueError("fixture is not valid JSON")
    if not isinstance(data, dict):
        raise ValueError("fixture must be a JSON object keyed by outcome")
    wanted = tuple(GUARD_OUTCOMES if guard else outcomes)
    extra = sorted(set(data) - set(wanted))
    if extra and guard:
        raise ValueError("fixture has unknown outcome(s) %s" % ", ".join(extra))
    parsed = {}
    for outcome in wanted:
        if outcome not in data:
            raise ValueError("fixture has no entry for outcome %s" % outcome)
        entry = data[outcome]
        try:
            if guard:
                parsed[outcome] = parse_guard_output(json.dumps(entry))
                expected = GUARD_PASS if parsed[outcome].passed else GUARD_FAIL
            else:
                parsed[outcome] = parse_stage_output(json.dumps(entry), wanted)
                expected = parsed[outcome].outcome
        except ValueError as e:
            raise ValueError("fixture entry %s: %s" % (outcome, e))
        if expected != outcome:
            raise ValueError("fixture entry %s names outcome %s" % (outcome, expected))
    return parsed
