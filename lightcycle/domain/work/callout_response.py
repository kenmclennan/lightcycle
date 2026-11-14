import json
import re
from dataclasses import dataclass
from typing import Tuple

PROTOCOL = 1
STATUSES = ("ok", "failed")
KINDS = ("link", "text", "markdown")
MAX_ARTIFACTS = 20
MAX_VALUE_CHARS = 65536
MAX_LABEL_CHARS = 80
_LINK = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://\S+$")


@dataclass(frozen=True)
class CalloutArtifact:
    label: str
    kind: str
    value: str


@dataclass(frozen=True)
class CalloutResponse:
    status: str
    message: str
    artifacts: Tuple[CalloutArtifact, ...] = ()


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
    if status == "failed" and not message.strip():
        return "message is required when status is failed"
    artifacts = raw.get("artifacts", [])
    if not isinstance(artifacts, list):
        return "artifacts must be a list"
    if len(artifacts) > MAX_ARTIFACTS:
        return "artifacts has more than %d entries" % MAX_ARTIFACTS
    for index, artifact in enumerate(artifacts, 1):
        problem = _artifact_problem(index, artifact)
        if problem:
            return problem
    return CalloutResponse(
        status=status, message=message,
        artifacts=tuple(CalloutArtifact(a["label"], a["kind"], a["value"]) for a in artifacts))
