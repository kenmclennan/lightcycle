from rich.text import Text

from lightcycle.adapters.tui.design_system import COLOURS, HEADING_STYLE
from lightcycle.application.inspect.resolve_references import ResolveReferencesUseCase
from lightcycle.domain.prose import HEADING, Reference, parse_prose, reference_ids


def resolve_titles(store, text):
    if not text:
        return {}
    ids = reference_ids(parse_prose(text))
    if not ids:
        return {}
    return ResolveReferencesUseCase(store).execute(ids)


def prose_text(text, titles, style=COLOURS["text"]):
    result = Text()
    for index, line in enumerate(parse_prose(text)):
        if index:
            result.append("\n")
        heading = line.kind == HEADING
        line_style = HEADING_STYLE if heading else style
        for segment in line.segments:
            if not isinstance(segment, Reference):
                result.append(segment.text, style=line_style)
                continue
            title = titles.get(segment.id)
            if title:
                result.append(title, style=line_style)
                tail = " (%s)" % segment.id
            else:
                result.append(segment.id, style=line_style)
                tail = " (not found)"
            result.append(tail, style=line_style if heading else COLOURS["dim"])
    return result
