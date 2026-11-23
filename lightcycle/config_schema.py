import math
import os
import re

from lightcycle.config_callouts import CALLOUT_KEY_PREFIX, callout_key_problem
from lightcycle.config_ranges import check_range, parse_bool
from lightcycle.config_schedules import SCHEDULE_KEY_PREFIX, WORKFLOW_KEY_PREFIX
from lightcycle.config_seeds import seed_key_names
from lightcycle.domain.schedule.cron import parse_cron

BOOL = "bool"
INT = "int"
FLOAT = "float"
PATH = "path"
RELATIVE_PATH = "relative-path"
LIST = "list"
STR = "str"

_BOOL_KEYS = (
    "tui-autostart-pool", "tui-health-icons", "tui-metrics", "developer-mode", "schedules-paused",
)
_FLOAT_KEYS = ("worktree-retry-sleep", "memory-reserve-fraction") + tuple(
    "price-%s-%s-per-mtok" % (model, kind)
    for model in ("sonnet", "opus", "haiku")
    for kind in ("input", "output", "cache-write", "cache-read")
)
_PATH_KEYS = ("projects", "backups-dir", "guidance-path", "specs-path")
_RELATIVE_PATH_KEYS = (
    "tui-health-icon-dir", "tui-health-icon-0", "tui-health-icon-1", "tui-health-icon-2",
    "tui-health-icon-3", "tui-health-icon-4", "tui-health-icon-busy",
)
_LIST_KEYS = ("trusted-authors", "review-bots", "context-artifact-types")
_STR_KEYS = (
    "branch-prefix", "default-origin", "workflows-remote", "editor", "personal-origin",
    "audit-shortcode", "held-comment-shortcode", "guidance-shortcode",
    "context-artifact-project",
)
_INT_KEYS = (
    "max-agents", "worktree-retries", "max-boot-seconds", "max-session-seconds", "stall-seconds",
    "ci-check-ceiling-seconds", "ci-start-window-seconds", "ci-no-workflows-wait-seconds",
    "ci-unconfirmed-note-polls", "release-hold-note-seconds", "probe-cooldown-seconds",
    "spin-cap", "poll-seconds", "github-poll-seconds", "github-reserve-calls",
    "github-view-refresh-polls", "tick-lag-window-seconds", "tick-lag-share",
    "tick-stall-seconds", "worker-history", "backup-interval-minutes", "guidance-fetch-minutes",
    "backup-retention", "workflow-retention", "max-title-length", "tui-upgrade-check-seconds",
    "tui-doctor-check-seconds", "pool-upgrade-check-seconds", "shutdown-grace-seconds",
    "tick-failure-cap", "review-rounds-cap", "guidance-budget-bytes",
    "guidance-unused-after-deliveries", "guidance-dormant-days", "lifecycle-timeout-seconds",
    "script-timeout-seconds", "script-max-running", "held-comment-triage-timeout",
)

KEY_KINDS = {}
for _kind, _keys in (
    (BOOL, _BOOL_KEYS), (INT, _INT_KEYS), (FLOAT, _FLOAT_KEYS), (PATH, _PATH_KEYS),
    (RELATIVE_PATH, _RELATIVE_PATH_KEYS), (LIST, _LIST_KEYS), (STR, _STR_KEYS),
):
    for _key in _keys:
        KEY_KINDS[_key] = _kind

BLANK_ALLOWED = ("personal-origin",)
NO_USABLE_DEFAULT = ("trusted-authors", "workflows-remote")
CASEFOLDED_LISTS = ("trusted-authors", "review-bots")

SEED = "seed"
BLOCK = "block"
BLOCK_KEY = "block-key"
CALLOUT = "callout"
SCHEDULE = "schedule"
WORKFLOW = "workflow"

_INNER = re.compile(r"^[a-z0-9-]+$")
_CALLOUT_ID = re.compile(r"^[a-z0-9-]+$")
_OTHER_ID = re.compile(r"^[A-Za-z0-9._-]+$")


class ConfigAddressError(ValueError):
    pass


class Address:
    def __init__(self, kind, key, family=None, block=None, inner=None):
        self.kind = kind
        self.key = key
        self.family = family
        self.block = block
        self.inner = inner


def _family(name):
    for prefix, family, pattern in (
        (CALLOUT_KEY_PREFIX, CALLOUT, _CALLOUT_ID),
        (SCHEDULE_KEY_PREFIX, SCHEDULE, _OTHER_ID),
        (WORKFLOW_KEY_PREFIX, WORKFLOW, _OTHER_ID),
    ):
        if name.startswith(prefix) and pattern.match(name[len(prefix):]):
            return family
    return None


def _unknown(key):
    near = [k for k in sorted(seed_key_names()) if key and (k.startswith(key) or key in k)]
    hint = " (did you mean %s?)" % near[0] if near else ""
    return ConfigAddressError("unknown config key '%s'%s" % (key, hint))


def resolve_address(key, existing_blocks=()):
    if key in KEY_KINDS:
        return Address(SEED, key)
    if key in existing_blocks and _family(key):
        return Address(BLOCK, key, family=_family(key), block=key)
    if "." in key:
        block, inner = key.rsplit(".", 1)
        family = _family(block)
        if family is None or not _INNER.match(inner):
            raise _unknown(key)
        return Address(BLOCK_KEY, key, family=family, block=block, inner=inner)
    family = _family(key)
    if family is None:
        raise _unknown(key)
    return Address(BLOCK, key, family=family, block=key)


def _single_line(key, raw, allow_blank=False):
    text = str(raw).strip()
    if "\n" in text or "\r" in text:
        raise ValueError("%s must be a single line" % key)
    if not text and not allow_blank:
        raise ValueError("%s must not be blank" % key)
    return text


def _number(key, text, parse):
    try:
        value = parse(text)
    except ValueError:
        raise ValueError("%s must be %s (got %r)" % (
            key, "a whole number" if parse is int else "a number", text))
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("%s must be a finite number (got %r)" % (key, text))
    check_range(key, value)
    return value


def list_token(key, raw):
    text = str(raw).strip()
    if not text or len(text.split()) != 1:
        raise ValueError("%s entries must be one non-blank token without spaces (got %r)" % (key, raw))
    return text


def normalize_seed_value(key, values):
    kind = KEY_KINDS[key]
    if kind == LIST:
        tokens = " ".join(str(v) for v in values).split()
        if not tokens:
            raise ValueError("%s must not be blank" % key)
        for token in tokens:
            _single_line(key, token)
        return " ".join(tokens)
    if len(values) != 1:
        raise ValueError("%s takes one value (got %d)" % (key, len(values)))
    text = _single_line(key, values[0], allow_blank=key in BLANK_ALLOWED)
    if kind == BOOL:
        return "true" if parse_bool(key, text) else "false"
    if kind == INT:
        return str(_number(key, text, int))
    if kind == FLOAT:
        _number(key, text, float)
        return text
    if kind == RELATIVE_PATH:
        parts = text.replace("\\", "/").split("/")
        if os.path.isabs(text) or ".." in parts:
            raise ValueError("%s must be relative and stay under the data root (got %r)" % (key, text))
    return text


def _bool_problem(key, text):
    try:
        parse_bool(key, text)
    except ValueError:
        return "%s must be true or false (got %r)" % (key, text)
    return None


def block_key_problem(family, inner, raw):
    key = inner
    try:
        text = _single_line(key, raw)
    except ValueError as e:
        return str(e)
    if family == CALLOUT:
        return callout_key_problem(inner, text)
    if family == SCHEDULE:
        if inner == "enabled":
            return _bool_problem(inner, text)
        if inner == "cron":
            try:
                parse_cron(text)
            except ValueError as e:
                return str(e)
        if inner == "name" and not _INNER.match(text):
            return "name must match [a-z0-9-]+ (got %r)" % text
    return None


def block_key_value(family, inner, values):
    if len(values) != 1:
        raise ValueError("%s takes one value (got %d)" % (inner, len(values)))
    text = _single_line(inner, values[0])
    problem = block_key_problem(family, inner, text)
    if problem:
        raise ValueError(problem)
    return text
