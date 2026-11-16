SLEEP_SLACK_SECONDS = 10
SLEEP_RETENTION_SECONDS = 24 * 3600


def _overlap(start, end, sleep):
    return max(0.0, min(end, sleep[1]) - max(start, sleep[0]))


def awake_elapsed(since, now, sleeps=()):
    asleep = sum(_overlap(since, now, s) for s in sleeps)
    return max(0.0, (now - since) - asleep)


def overlaps_sleep(start, end, sleeps=()):
    return any(_overlap(start, end, s) > 0 for s in sleeps)


def detect_sleep(sample, wall_now, awake_now):
    if sample is None:
        return None
    sample_wall, sample_awake = sample
    if awake_now < sample_awake:
        return None
    gap = (wall_now - sample_wall) - (awake_now - sample_awake)
    if gap <= SLEEP_SLACK_SECONDS:
        return None
    return (wall_now - gap, wall_now)
