import re

_BACKTICKED = re.compile(r"`([^`\n]+)`")
_LC_CALL = re.compile(r"^lc\s+([a-z][a-z-]*)\b(.*)$", re.S)
_FLAG = re.compile(r"(?<![\w-])--([a-z][a-z-]*)")
_STATE = re.compile(r"--state\s+([a-z_]+)")
_QUOTED = re.compile(r"\"[^\"]*\"|'[^']*'")


def _outside_quotes(text):
    return _QUOTED.sub(" ", text)


def lc_calls(text):
    calls = []
    for line_no, line in enumerate(text.splitlines(), 1):
        for span in _BACKTICKED.findall(line):
            call = _LC_CALL.match(span.strip())
            if call is None:
                continue
            verb, rest = call.group(1), call.group(2)
            rest = _outside_quotes(rest)
            state = _STATE.search(rest)
            calls.append(
                {
                    "line": line_no,
                    "verb": verb,
                    "flags": set(_FLAG.findall(rest)),
                    "state": state.group(1) if state else None,
                    "text": span.strip(),
                }
            )
    return calls


_FIELD_READ = re.compile(r"`\.([a-z][a-z_]*)`")

FILE_EXTENSIONS = frozenset(
    {"feature", "md", "py", "json", "toml", "yml", "yaml", "sh", "tcss", "styles", "txt"}
)


def json_field_reads(text, extensions=FILE_EXTENSIONS):
    reads = []
    for line_no, line in enumerate(text.splitlines(), 1):
        for field in _FIELD_READ.findall(line):
            if field in extensions:
                continue
            reads.append({"line": line_no, "field": field})
    return reads
