import re
from dataclasses import dataclass, field
from typing import Optional, Tuple

from lightcycle.domain.schedule.cron import parse_cron
from lightcycle.domain.schedule.guards import parse_guard_params

SOURCE_BUNDLE = "bundle"
SOURCE_CONFIG = "config"
SOURCE_BOTH = "both"

_ID = re.compile(r"^[a-z0-9-]+$")
_TRUE = ("true", "yes", "1", "on")
_FALSE = ("false", "no", "0", "off")
_RESERVED = ("enabled", "workflow", "project", "cron", "guard", "shortcode", "labels", "name")


@dataclass(frozen=True)
class Schedule:
    id: str
    source: str
    enabled: bool
    workflow: Optional[str]
    project: Optional[str]
    cron: Optional[str]
    guard: Optional[str]
    params: dict = field(default_factory=dict)
    shortcode: Optional[str] = None
    labels: Tuple[str, ...] = ()
    problem: Optional[str] = None
    explicit_off: bool = False
    name: Optional[str] = None


def _suggestion_fields(suggestion):
    return dict(suggestion) if isinstance(suggestion, dict) else {}


def _problem_of(id, enabled_text, workflow, project, cron, guard, params, has_block, name=None):
    if not _ID.match(id) and has_block:
        return "id must match [a-z0-9-]+"
    if has_block:
        if enabled_text is None:
            return "config block has no enabled line"
        if enabled_text.strip().lower() not in _TRUE + _FALSE:
            return "enabled must be true or false (got %r)" % enabled_text
        if not workflow:
            return "config block has no workflow"
        if not project:
            return "config block has no project"
    if name is not None and not _ID.match(name):
        return "name must match [a-z0-9-]+"
    if not cron:
        return "no cron from config or the bundle suggestion"
    if not guard:
        return "no guard from config or the bundle suggestion"
    try:
        parse_cron(cron)
    except ValueError as e:
        return str(e)
    try:
        parse_guard_params(guard, params)
    except ValueError as e:
        return str(e)
    return None


def _typed_params(guard, params, problem):
    if problem is not None or not guard:
        return params
    return parse_guard_params(guard, params)


def merge_schedule(id, block, suggestion, workflow=None):
    has_block = block is not None
    block = dict(block or {})
    suggested = _suggestion_fields(suggestion)
    cron = block.get("cron") or suggested.get("cron")
    guard = block.get("guard") or suggested.get("guard")
    merged = {k: v for k, v in suggested.items() if k not in _RESERVED}
    merged.update({k: v for k, v in block.items() if k not in _RESERVED})
    name = (str(block.get("name") or suggested.get("name") or "").strip()) or None
    workflow = block.get("workflow") or workflow
    project = block.get("project")
    enabled_text = block.get("enabled")
    enabled = has_block and enabled_text is not None and enabled_text.strip().lower() in _TRUE
    if not has_block:
        source = SOURCE_BUNDLE
    elif suggested:
        source = SOURCE_BOTH
    else:
        source = SOURCE_CONFIG
    problem = _problem_of(id, enabled_text, workflow, project, cron, guard, merged, has_block, name)
    return Schedule(
        id=id, source=source, enabled=enabled, workflow=workflow, project=project,
        cron=cron, guard=guard, params=_typed_params(guard, merged, problem),
        shortcode=block.get("shortcode") or None,
        labels=tuple((block.get("labels") or "").split()),
        problem=problem, name=name,
        explicit_off=has_block and enabled_text is not None
        and enabled_text.strip().lower() in _FALSE,
    )
