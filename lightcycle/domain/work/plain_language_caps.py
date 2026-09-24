import re
from dataclasses import dataclass
from typing import Optional

MAX_PARAGRAPHS = 3
MAX_WORDS = 180
MAX_SENTENCES_PER_PARAGRAPH = 4
MAX_SENTENCE_WORDS = 30

_EXCERPT_WORDS = 10
_FENCE_RE = re.compile(r"```.*?(?:```|\Z)", re.S)
_PARAGRAPH_BREAK_RE = re.compile(r"\n\s*\n")
_CODE_SPAN_RE = re.compile(r"`[^`\n]*`")
_DOUBLE_QUOTE_RE = re.compile(r'"[^"]*"')
_SINGLE_QUOTE_RE = re.compile(r"(?<!\w)'(?=[^\s'])(.*?)(?<=\S)'(?!\w)", re.S)
_LIST_MARKER_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
_SENTENCE_END_RE = re.compile(r"^(?P<stem>.*?)[.!?]+[\"')\]]*$")
_ENUMERATOR_RE = re.compile(r"^\(?\d+\)?$")
_ABBREVIATIONS = frozenset(("e.g", "i.e", "vs", "cf", "approx"))
_BREAK = "\x01"
_SPAN_MARK = "\x00"


@dataclass(frozen=True)
class CapBreach:
    rule: int
    kind: str
    count: int
    limit: int
    excerpt: Optional[str] = None
    paragraph: Optional[int] = None


def _is_word(token):
    return any(ch.isalnum() for ch in token)


def _mask_code_spans(text):
    spans = []

    def mask(match):
        spans.append(match.group(0))
        return "%s%d%s" % (_SPAN_MARK, len(spans) - 1, _SPAN_MARK)

    return _CODE_SPAN_RE.sub(mask, text), spans


def _mask_quotes(paragraph, spans):
    def mask(match):
        spans.append(match.group(0))
        return "%s%d%s" % (_SPAN_MARK, len(spans) - 1, _SPAN_MARK)

    def mask_single(match):
        return mask(match) if len(match.group(1).split()) > 1 else match.group(0)

    return _SINGLE_QUOTE_RE.sub(mask_single, _DOUBLE_QUOTE_RE.sub(mask, paragraph))


_MARKER_RE = re.compile("%s(\\d+)%s" % (_SPAN_MARK, _SPAN_MARK))


def _unmask(text, spans):
    while _MARKER_RE.search(text):
        text = _MARKER_RE.sub(lambda m: spans[int(m.group(1))], text)
    return text


def _segments(paragraph):
    marked = []
    for line in paragraph.split("\n"):
        stripped = _LIST_MARKER_RE.sub("", line)
        marked.append(_BREAK + stripped if stripped != line else line)
    return " ".join(marked).split(_BREAK)


def _ends_sentence(token):
    match = _SENTENCE_END_RE.match(token)
    if match is None:
        return False
    stem = match.group("stem").lower()
    return stem not in _ABBREVIATIONS and not _ENUMERATOR_RE.match(stem)


def _sentences(paragraph):
    sentences = []
    for segment in _segments(paragraph):
        tokens = segment.split()
        current = []
        for index, token in enumerate(tokens):
            current.append(token)
            if index + 1 < len(tokens) and _ends_sentence(token):
                sentences.append(current)
                current = []
        if current:
            sentences.append(current)
    return [s for s in sentences if any(_is_word(t) for t in s)]


def _count_words(tokens):
    return sum(1 for t in tokens if _is_word(t))


def cap_breaches(text):
    if not text:
        return ()
    masked, spans = _mask_code_spans(_FENCE_RE.sub("", text))
    paragraphs = []
    for chunk in _PARAGRAPH_BREAK_RE.split(masked):
        sentences = _sentences(_mask_quotes(chunk, spans))
        if sentences:
            paragraphs.append(sentences)

    long_sentences = []
    crowded = []
    total_words = 0
    for number, sentences in enumerate(paragraphs, start=1):
        total_words += sum(_count_words(s) for s in sentences)
        for tokens in sentences:
            words = _count_words(tokens)
            if words > MAX_SENTENCE_WORDS:
                long_sentences.append(CapBreach(
                    3, "sentence", words, MAX_SENTENCE_WORDS,
                    excerpt=_unmask(" ".join(tokens), spans), paragraph=number,
                ))
        if len(sentences) > MAX_SENTENCES_PER_PARAGRAPH:
            opening = [t for s in sentences for t in s][:_EXCERPT_WORDS]
            crowded.append(CapBreach(
                2, "sentences", len(sentences), MAX_SENTENCES_PER_PARAGRAPH,
                excerpt=_unmask(" ".join(opening), spans), paragraph=number,
            ))

    breaches = long_sentences + crowded
    if total_words > MAX_WORDS:
        breaches.append(CapBreach(2, "words", total_words, MAX_WORDS))
    if len(paragraphs) > MAX_PARAGRAPHS:
        breaches.append(CapBreach(2, "paragraphs", len(paragraphs), MAX_PARAGRAPHS))
    return tuple(breaches)


def _render_breach(label, breach):
    if breach.kind == "sentence":
        return '%s, rule 3: a sentence of %d words, at most %d: "%s"' % (
            label, breach.count, breach.limit, breach.excerpt,
        )
    if breach.kind == "sentences":
        return '%s, rule 2: paragraph %d has %d sentences, at most %d: "%s ..."' % (
            label, breach.paragraph, breach.count, breach.limit, breach.excerpt,
        )
    return "%s, rule 2: %d %s, at most %d" % (label, breach.count, breach.kind, breach.limit)


def render_cap_refusal(fields):
    lines = []
    labels = []
    for label, text in fields:
        breaches = cap_breaches(text)
        if breaches:
            labels.append(label)
            lines.extend(_render_breach(label, b) for b in breaches)
    if not lines:
        return ""
    verb = "breaks" if len(labels) == 1 else "break"
    header = (
        "refused: %s %s the plain-language caps (rules 2 and 3), so nothing was stored. "
        "Shorten the text and run the command again; do not drop it."
        % (", ".join(labels), verb)
    )
    return "\n".join([header] + lines)
