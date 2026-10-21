import fnmatch
import re

PART = re.compile(r"^[A-Za-z0-9_*?\[][A-Za-z0-9_.*?\[\]!-]*$")


def validate_element(text):
    parts = text.split("+")
    return all(PART.match(part) for part in parts)


def parse_detected_by(items):
    if items is None:
        return None
    if not all(validate_element(item) for item in items):
        return None
    return tuple(items)


def _first_match(part, paths):
    for path in sorted(paths):
        if fnmatch.fnmatchcase(path.rsplit("/", 1)[-1], part):
            return path
    return None


def _match_element(element, paths):
    found = []
    for part in element.split("+"):
        path = _first_match(part, paths)
        if path is None:
            return None
        found.append(path)
    return " + ".join(found)


def detect(rules, paths):
    suggestions = []
    for facet in sorted(rules):
        for element in rules[facet]:
            matched = _match_element(element, paths)
            if matched is not None:
                suggestions.append((facet, matched))
                break
    return suggestions
