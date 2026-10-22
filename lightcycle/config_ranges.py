_TRUE = ("true", "yes", "1", "on")
_FALSE = ("false", "no", "0", "off")

_NUMERIC_RANGES = {
    "github-poll-seconds": (1, None),
    "github-reserve-calls": (0, None),
    "github-view-refresh-polls": (1, None),
    "memory-reserve-fraction": (0.0, 1.0),
    "max-agents": (0, None),
    "guidance-budget-bytes": (0, None),
    "guidance-unused-after-deliveries": (1, None),
    "guidance-dormant-days": (1, None),
    "lifecycle-timeout-seconds": (1, None),
    "script-timeout-seconds": (1, None),
    "script-max-running": (1, None),
    "workflow-retention": (1, None),
    "max-boot-seconds": (0, None),
    "max-session-seconds": (0, None),
    "stall-seconds": (0, None),
    "ci-check-ceiling-seconds": (1, None),
    "ci-start-window-seconds": (1, None),
    "ci-no-workflows-wait-seconds": (1, None),
    "ci-unconfirmed-note-polls": (1, None),
    "release-hold-note-seconds": (1, None),
    "probe-cooldown-seconds": (0, None),
    "tui-upgrade-check-seconds": (0, None),
    "pool-upgrade-check-seconds": (0, None),
    "shutdown-grace-seconds": (0, None),
    "price-sonnet-input-per-mtok": (0.0, None),
    "price-sonnet-output-per-mtok": (0.0, None),
    "price-sonnet-cache-write-per-mtok": (0.0, None),
    "price-sonnet-cache-read-per-mtok": (0.0, None),
    "price-opus-input-per-mtok": (0.0, None),
    "price-opus-output-per-mtok": (0.0, None),
    "price-opus-cache-write-per-mtok": (0.0, None),
    "price-opus-cache-read-per-mtok": (0.0, None),
    "price-haiku-input-per-mtok": (0.0, None),
    "price-haiku-output-per-mtok": (0.0, None),
    "price-haiku-cache-write-per-mtok": (0.0, None),
    "price-haiku-cache-read-per-mtok": (0.0, None),
}


def check_range(key, value):
    bounds = _NUMERIC_RANGES.get(key)
    if bounds is None:
        return value
    lo, hi = bounds
    if lo is not None and value < lo:
        raise ValueError("config value %r must be >= %r (got %r)" % (key, lo, value))
    if hi is not None and value > hi:
        raise ValueError("config value %r must be <= %r (got %r)" % (key, hi, value))
    return value


def parse_bool(key, raw):
    text = str(raw).strip().lower()
    if text in _TRUE:
        return True
    if text in _FALSE:
        return False
    raise ValueError(
        "config value %r must be one of %s or %s (got %r)"
        % (key, "/".join(_TRUE), "/".join(_FALSE), raw))
