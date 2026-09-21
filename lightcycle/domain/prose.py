import re
from collections import namedtuple

ProseLine = namedtuple("ProseLine", "kind segments")
Literal = namedtuple("Literal", "text")
Reference = namedtuple("Reference", "id")

HEADING = "heading"
BODY = "body"

_HEADING_RE = re.compile(r"^#{1,6}[ \t]+(?=\S)")
_REFERENCE_RE = re.compile(r"\[\[([A-Za-z][A-Za-z0-9]*-\d+(?:\.\d+)*)\]\]")


def _segments(text):
    segments = []
    position = 0
    for match in _REFERENCE_RE.finditer(text):
        if match.start() > position:
            segments.append(Literal(text[position:match.start()]))
        segments.append(Reference(match.group(1)))
        position = match.end()
    if position < len(text) or not segments:
        segments.append(Literal(text[position:]))
    return tuple(segments)


def parse_prose(text):
    lines = []
    in_fence = False
    for raw in text.split("\n"):
        if raw.strip().startswith("```"):
            in_fence = not in_fence
            lines.append(ProseLine(BODY, (Literal(raw),)))
            continue
        if in_fence:
            lines.append(ProseLine(BODY, (Literal(raw),)))
            continue
        heading = _HEADING_RE.match(raw)
        if heading:
            lines.append(ProseLine(HEADING, _segments(raw[heading.end():])))
        else:
            lines.append(ProseLine(BODY, _segments(raw)))
    return lines


def reference_ids(lines):
    seen = []
    for line in lines:
        for segment in line.segments:
            if isinstance(segment, Reference) and segment.id not in seen:
                seen.append(segment.id)
    return seen
