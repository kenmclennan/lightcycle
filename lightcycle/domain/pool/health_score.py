from lightcycle.domain.workflows.engine_requirement import parse_version

POOL_STATES = (
    "running", "starting", "stopping", "draining", "start-timed-out", "stop-timed-out", "stopped",
)

_IN_MOTION = ("starting", "stopping", "draining")
_FAILED = ("start-timed-out", "stop-timed-out", "stopped")


def pool_health_score(state, tick_level, median_seconds, poll_seconds):
    if state in _IN_MOTION:
        return 1
    if state in _FAILED:
        return 4
    if tick_level == "stalled":
        return 4
    if tick_level == "lagging":
        if median_seconds is None or median_seconds <= 2 * poll_seconds:
            return 1
        if median_seconds <= 4 * poll_seconds:
            return 2
        return 3
    return 0


def claude_health_score(breaker_is_open):
    return 4 if breaker_is_open else 0


def github_health_score(remaining, limit):
    if remaining is None or limit is None or limit <= 0:
        return 0
    pct = remaining * 100 // limit
    if pct >= 81:
        return 0
    if pct >= 61:
        return 1
    if pct >= 41:
        return 2
    if pct >= 21:
        return 3
    return 4


_STALE_RELEASES = 3
_MAINTENANCE_CAP = 3


def releases_behind(installed, available):
    try:
        have = parse_version(installed)
        want = parse_version(available)
    except ValueError:
        return None
    if want <= have:
        return 0
    if want[:2] != have[:2]:
        return _STALE_RELEASES
    return want[2] - have[2]


def maintenance_health_score(upgrade_available, behind, config_changed, doctor_findings, orphans):
    score = sum(1 for pending in (upgrade_available, config_changed, doctor_findings, orphans) if pending)
    if upgrade_available and behind is not None and behind >= _STALE_RELEASES:
        score += 1
    return min(score, _MAINTENANCE_CAP)


def health_score(pool, claude, github, maintenance):
    return max(pool, claude, github, maintenance)


def health_image_state(score, busy):
    if score == 0 and busy:
        return "busy"
    return str(score)
