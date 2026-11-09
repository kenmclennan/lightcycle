def parse_counts(text):
    counts = {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        path, _, count = line.partition(":")
        counts[path.strip()] = int(count.strip())
    return counts


def grown_entries(before, after):
    grown = {}
    for key, after_count in after.items():
        before_count = before.get(key, 0)
        if after_count > before_count:
            grown[key] = (before_count, after_count)
    return grown


def stale_entries(before, after):
    stale = {}
    for key, before_count in before.items():
        after_count = after.get(key, 0)
        if before_count > after_count:
            stale[key] = (before_count, after_count)
    return stale


def stale_message(stale):
    return "baseline allows more than the live count; lower or delete these lines: %s" % ", ".join(
        "%s: baseline %d, live %d" % (key, b, a) for key, (b, a) in sorted(stale.items())
    )
