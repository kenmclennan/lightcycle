import json
import math
import re
from dataclasses import dataclass
from typing import Optional, Tuple

PROTOCOL = 2
STATUSES = ("ok", "failed")
KINDS = ("link", "text", "markdown")
MAX_ARTIFACTS = 20
MAX_VALUE_CHARS = 65536
MAX_LABEL_CHARS = 80
MAX_ERRORS = 20
MAX_USAGE_COST_USD = 1000000
MAX_ERROR_CHARS = 500
_LINK = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://\S+$")


@dataclass(frozen=True)
class CalloutArtifact:
    label: str
    kind: str
    value: str


@dataclass(frozen=True)
class CalloutError:
    message: str
    fix: str


@dataclass(frozen=True)
class CalloutUsage:
    cost_usd: float
    model: Optional[str] = None


@dataclass(frozen=True)
class CalloutResponse:
    status: str
    message: str
    artifacts: Tuple[CalloutArtifact, ...] = ()
    errors: Tuple[CalloutError, ...] = ()
    usage: Optional[CalloutUsage] = None


@dataclass(frozen=True)
class PreflightResponse:
    status: str
    errors: Tuple[CalloutError, ...] = ()


def _errors_problem(raw):
    if not isinstance(raw, list):
        return "errors must be a list"
    if len(raw) > MAX_ERRORS:
        return "errors has more than %d entries" % MAX_ERRORS
    for index, entry in enumerate(raw, 1):
        where = "error %d" % index
        if not isinstance(entry, dict):
            return "%s is not an object" % where
        for key in ("message", "fix"):
            value = entry.get(key)
            if not isinstance(value, str) or not value:
                return "%s key %r must be a non-empty string" % (where, key)
            if len(value) > MAX_ERROR_CHARS:
                return "%s %s is longer than %d characters" % (where, key, MAX_ERROR_CHARS)
    return None


def _errors_of(raw):
    return tuple(CalloutError(e["message"], e["fix"]) for e in raw)


def validate_preflight_response(text):
    try:
        raw = json.loads(text)
    except (TypeError, ValueError):
        return "stdout is not a JSON object"
    if not isinstance(raw, dict):
        return "stdout is not a JSON object"
    status = raw.get("status")
    if status not in STATUSES:
        return "status must be one of %s" % ", ".join(STATUSES)
    errors = raw.get("errors", [])
    problem = _errors_problem(errors)
    if problem:
        return problem
    if status == "failed" and not errors:
        return "errors is required when status is failed"
    if status == "ok" and errors:
        return "errors must be empty when status is ok"
    return PreflightResponse(status=status, errors=_errors_of(errors))


def _artifact_problem(index, raw):
    where = "artifact %d" % index
    if not isinstance(raw, dict):
        return "%s is not an object" % where
    for key in ("label", "kind", "value"):
        if not isinstance(raw.get(key), str) or not raw[key]:
            return "%s key %r must be a non-empty string" % (where, key)
    if raw["kind"] not in KINDS:
        return "%s kind %r is not one of %s" % (where, raw["kind"], ", ".join(KINDS))
    if len(raw["label"]) > MAX_LABEL_CHARS:
        return "%s label is longer than %d characters" % (where, MAX_LABEL_CHARS)
    if len(raw["value"]) > MAX_VALUE_CHARS:
        return "%s value is longer than %d characters" % (where, MAX_VALUE_CHARS)
    if raw["kind"] == "link" and not _LINK.match(raw["value"]):
        return "%s link value must be one token of the form <scheme>://<rest>" % where
    return None


def _usage_of(raw):
    if not isinstance(raw, dict):
        return "usage must be an object"
    cost = raw.get("cost_usd")
    if (
        isinstance(cost, bool) or not isinstance(cost, (int, float))
        or not math.isfinite(cost) or cost < 0 or cost > MAX_USAGE_COST_USD
    ):
        return "usage cost_usd must be a number between 0 and %d" % MAX_USAGE_COST_USD
    model = raw.get("model")
    if model is not None:
        if not isinstance(model, str) or not model:
            return "usage model must be a non-empty string"
        if len(model) > MAX_LABEL_CHARS:
            return "usage model is longer than %d characters" % MAX_LABEL_CHARS
    return CalloutUsage(cost_usd=cost, model=model)


def validate_callout_response(text):
    try:
        raw = json.loads(text)
    except (TypeError, ValueError):
        return "stdout is not a JSON object"
    if not isinstance(raw, dict):
        return "stdout is not a JSON object"
    status = raw.get("status")
    if status not in STATUSES:
        return "status must be one of %s" % ", ".join(STATUSES)
    message = raw.get("message", "")
    if not isinstance(message, str):
        return "message must be a string"
    errors = raw.get("errors", [])
    problem = _errors_problem(errors)
    if problem:
        return problem
    if status == "failed" and not message.strip() and not errors:
        return "message is required when status is failed"
    if status == "ok" and errors:
        return "errors must be empty when status is ok"
    artifacts = raw.get("artifacts", [])
    if not isinstance(artifacts, list):
        return "artifacts must be a list"
    if len(artifacts) > MAX_ARTIFACTS:
        return "artifacts has more than %d entries" % MAX_ARTIFACTS
    for index, artifact in enumerate(artifacts, 1):
        problem = _artifact_problem(index, artifact)
        if problem:
            return problem
    usage = None
    if "usage" in raw:
        usage = _usage_of(raw["usage"])
        if isinstance(usage, str):
            return usage
    return CalloutResponse(
        status=status, message=message,
        artifacts=tuple(CalloutArtifact(a["label"], a["kind"], a["value"]) for a in artifacts),
        errors=_errors_of(errors), usage=usage)
