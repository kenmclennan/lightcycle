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
