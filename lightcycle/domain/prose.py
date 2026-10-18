import re
from collections import namedtuple

ProseLine = namedtuple("ProseLine", "kind segments")
Literal = namedtuple("Literal", "text")
Reference = namedtuple("Reference", "id")
Link = namedtuple("Link", "text url")

HEADING = "heading"
BODY = "body"

_HEADING_RE = re.compile(r"^#{1,6}[ \t]+(?=\S)")
_TOKEN_RE = re.compile(
    r"\[\[(?P<ref>[A-Za-z][A-Za-z0-9]*-\d+(?:\.\d+)*)\]\]"
    r"|\[(?P<label>[^\[\]]+)\]\((?P<md>https?://[^\s)]+)\)"
    r"|(?P<bare>https?://[^\s<>)\]]*[^\s<>)\].,;:!?'\"])"
)


def _segments(text):
    segments = []
    position = 0
    for match in _TOKEN_RE.finditer(text):
        if match.start() > position:
            segments.append(Literal(text[position:match.start()]))
        if match.group("ref"):
            segments.append(Reference(match.group("ref")))
        elif match.group("md"):
            segments.append(Link(match.group("label"), match.group("md")))
        else:
            segments.append(Link(match.group("bare"), match.group("bare")))
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
