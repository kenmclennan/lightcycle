from dataclasses import dataclass

from lightcycle.adapters.tui.design_system import FILTER_ROW_LABEL_WIDTH, SEARCH_MIN_WIDTH

FILTER_ROW_GAP = 2
ELLIPSIS = "…"


@dataclass(frozen=True)
class FilterRowLine:
    segments: tuple
    count: str | None


@dataclass(frozen=True)
class FilterRowLayout:
    lines: tuple
    search_width: int


def segment_width(segment) -> int:
    label, value = segment
    return len(label) + 1 + len(value)


def _fit_segment(label, value, width):
    if len(label) + 1 + len(value) <= width:
        return (label, value)
    room = max(width - len(label) - 1, 1)
    return (label, value[: room - 1] + ELLIPSIS)


def flow_filter_row(
    width,
    segments,
    count_text=None,
    min_search=SEARCH_MIN_WIDTH,
    label_width=FILTER_ROW_LABEL_WIDTH,
    gap=FILTER_ROW_GAP,
) -> FilterRowLayout:
    base = label_width + min_search
    first = []
    used_first = base
    later = []
    moved = False
    for label, value in segments:
        segment = _fit_segment(label, value, width)
        seg_w = segment_width(segment)
        if not moved and used_first + gap + seg_w <= width:
            first.append(segment)
            used_first += gap + seg_w
            continue
        moved = True
        if later and later[-1][1] + gap + seg_w <= width:
            later[-1][0].append(segment)
            later[-1][1] += gap + seg_w
        else:
            later.append([[segment], seg_w])

    count_on_first = False
    count_line = None
    if count_text:
        count_w = len(count_text)
        if not later:
            if used_first + gap + count_w <= width:
                count_on_first = True
            else:
                count_line = True
        elif later[-1][1] + gap + count_w <= width:
            later[-1].append(count_text)
        else:
            count_line = True

    lines = [FilterRowLine(tuple(first), count_text if count_on_first else None)]
    for entry in later:
        count = entry[2] if len(entry) == 3 else None
        lines.append(FilterRowLine(tuple(entry[0]), count))
    if count_line:
        lines.append(FilterRowLine((), count_text))

    taken = used_first - base
    if count_on_first:
        taken += gap + len(count_text)
    search_width = max(min_search, width - label_width - taken)
    return FilterRowLayout(tuple(lines), search_width)
