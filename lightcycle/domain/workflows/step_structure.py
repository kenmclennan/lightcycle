import re

_ITEM = re.compile(r"^(\d+)\. ")
_HEADING = re.compile(r"^#{1,6} ")
_INDENTED_INCLUDE = re.compile(r"^\s+@include (\S.*)$")
_MID_LINE_INCLUDE = re.compile(r"\S\s+(@include (\S+))\s*$")
_INCLUDE = "@include "


def _fence_toggles(line):
    stripped = line.lstrip()
    return stripped.startswith("```") or stripped.startswith("~~~")


def _numbering(lines):
    problems = []
    fenced = False
    previous = None
    for number, line in enumerate(lines, 1):
        if _fence_toggles(line):
            fenced = not fenced
            continue
        if fenced:
            continue
        if _HEADING.match(line):
            previous = None
            continue
        match = _ITEM.match(line)
        if not match:
            continue
        value = int(match.group(1))
        if previous is None and value != 1:
            problems.append(
                "line %d: top-level list starts at %d (expected 1)" % (number, value)
            )
        elif previous is not None and value != previous + 1:
            problems.append(
                "line %d: top-level list item %d follows %d (expected %d)"
                % (number, value, previous, previous + 1)
            )
        previous = value
    return problems


def _includes(lines, fragment_names):
    problems = []
    fenced = False
    available = ", ".join(sorted(fragment_names))
    for number, line in enumerate(lines, 1):
        if _fence_toggles(line):
            fenced = not fenced
            continue
        if line.startswith(_INCLUDE):
            name = line[len(_INCLUDE):].strip()
            if name and name not in fragment_names:
                problems.append(
                    "line %d: @include %s does not resolve in a pinned bundle "
                    "(available fragments: %s)" % (number, name, available)
                )
            above = lines[number - 2] if number > 1 else ""
            if above.strip() and not _fence_toggles(above) and not fenced:
                problems.append(
                    "line %d: @include %s has text directly above it; prettier joins "
                    "the two lines - put a blank line before it" % (number, name)
                )
            continue
        if fenced:
            continue
        joined = _MID_LINE_INCLUDE.search(line)
        if joined and line[: joined.start(1)].count("`") % 2 == 0:
            problems.append(
                "line %d: @include %s is mid-line and will not resolve; put it on its "
                "own line with a blank line above" % (number, joined.group(2))
            )
            continue
        indented = _INDENTED_INCLUDE.match(line)
        if indented:
            problems.append(
                "line %d: @include %s is indented; the engine only resolves it at column 0"
                % (number, indented.group(1).strip())
            )
    return problems


def check_step_structure(step_texts, fragment_names):
    found = {}
    for name, text in sorted(step_texts.items()):
        lines = text.splitlines()
        problems = sorted(
            _numbering(lines) + _includes(lines, fragment_names),
            key=lambda m: int(m.split(":", 1)[0].split()[1]),
        )
        if problems:
            found[name] = problems
    return found
