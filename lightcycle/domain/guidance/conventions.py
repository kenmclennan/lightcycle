import re

CONVENTIONS_VERSION = 2

CONVENTIONS_TEXT = """# Conventions

Conventions version: """ + str(CONVENTIONS_VERSION) + """

This guidance repo follows the Open Knowledge Format (OKF) 0.2 with the lightcycle profile below.

## Entries

- An entry is one markdown file with front matter. Its id is its path from the repo root without `.md`, for example `testing/pg-tests-use-testcontainers`. Files named `index.md` are never entries.
- `type: Guidance` marks an entry lightcycle may deliver to an agent. Pages without it are ordinary concept pages, linked from entries.
- Every guidance entry has an `applies-to` mapping. An entry without one is malformed and never delivered.
- `applies-to` may hold `facets` and `steps`, each written as an inline list on one line: `facets: [kotlin, spring-boot]`. A block list (`- kotlin` on the next line) is malformed.
- `facets`: every facet listed must be declared on the project (`lc project set <repo> --facets ...`). No facets means every project.
- `steps`: a bare name (`write-code`) matches that step in any workflow origin; `<origin>/<step>` matches it in that origin only. No steps means every step.
- Every guidance entry carries three required front-matter fields, each one non-empty line, none delivered to a worker: `purpose` (the problem the entry solves), `when` (the circumstances in which it helps) and `why` (why this approach over the alternatives).
- An entry names no item id anywhere in the file. Where a finding came from lives on the `guidance-entry` item.
- A change that touches only `purpose`, `when` and `why` leaves `status`, `verified` and the body byte-identical, and the entry keeps its `stable` status.
- `covers: <issue url>` marks an entry that stands in for an upstream fix until that issue ships.

## Facets

A facet is valid only when this repo has a concept page named for it, anywhere in the tree (for example `languages/kotlin.md`). `lc doctor` reports a project facet or an `applies-to` facet with no page.

## Status

- `status: stable` is delivered once it is on the default branch. Merging the pull request that sets it is the human approval. `verified` is optional free text and is ignored for delivery.
- `status: draft` is never delivered.
- `status: deprecated` is retired and never delivered.

## Delivery

Matching entries are appended to a worker's system prompt at spawn: entries naming the step first, then the rest, each group by id. The entry bodies delivered to one spawn are capped by `guidance-budget-bytes`; an entry that does not fit is skipped whole. Keep entries short so they fit.

A worker cites the entries that changed what it did. An entry delivered many times and never cited is a candidate for removal.

## Changes

Entries change by pull request only. Nothing is written to the default branch directly.

## Checks

`lc guidance-check [--dir PATH] [--mode draft|final] [--base REF]` enforces these rules over every `.md` file changed in `BASE...HEAD`, except files named `index.md` or `CONVENTIONS.md`. It exits 1 on any failure or when it cannot read the base.

Both modes run the same rules:

1. A deleted entry fails: retire it with `status: deprecated` instead.
2. Front matter that is missing, unclosed or malformed fails.
3. A `type: Guidance` entry with no `applies-to` mapping fails.
4. `facets` or `steps` that is not an inline list on one line fails.
5. A facet with no `<facet>.md` concept page anywhere in the tree fails.
6. A step that is not a bare name or `<origin>/<step>` fails.
7. A `status` other than `draft`, `stable` or `deprecated` fails.
8. A missing or empty `purpose`, `when` or `why` fails, one failure per field.
9. An item id anywhere in the file fails, one failure per match.
10. A changed file without `type: Guidance` that no changed entry names as a facet fails.
"""

STEP = re.compile(r"^([a-z0-9][a-z0-9-]*/)?[a-z0-9][a-z0-9-]*$")
LIST = re.compile(r"^\[(.*)\]$")
ITEM_ID = re.compile(r"\b([A-Z][A-Z0-9]*)-\d+(?:\.\d+)*\b")
NON_ITEM = {"UTF", "SHA", "ISO", "RFC", "CVE", "TLS", "SSL", "HTTP", "AES", "IEEE", "PEP"}
CONTEXT = ("purpose", "when", "why")
SKIPPED_NAMES = ("index.md", "CONVENTIONS.md")


def parse(text):
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration:
        return None
    top, nested, section = {}, {}, None
    for raw in lines[1:end]:
        if not raw.strip():
            continue
        if raw.strip().startswith("-"):
            continue
        key, sep, value = raw.strip().partition(":")
        if not sep:
            return None
        if raw[0] in " \t":
            if section is None:
                return None
            nested.setdefault(section, {})[key.strip()] = value.strip()
        else:
            top[key.strip()] = value.strip()
            section = key.strip() if not value.strip() else None
    return top, nested


def item_ids(text):
    return [m.group(0) for m in ITEM_ID.finditer(text) if m.group(1) not in NON_ITEM]


def inline_list(value):
    match = LIST.match(value)
    if not match:
        return None
    return [item.strip() for item in match.group(1).split(",") if item.strip()]


def is_checked_path(path):
    name = path.rsplit("/", 1)[-1]
    return path.endswith(".md") and name not in SKIPPED_NAMES


def check_entries(mode, changed, deleted, facet_pages, read_head, read_base):
    failures = []

    for path in deleted:
        base_text = read_base(path)
        old = parse(base_text) if base_text is not None else None
        if old and old[0].get("type") == "Guidance":
            failures.append("%s: entry deleted - retire it with status: deprecated instead" % path)

    parsed = {}
    texts = {}
    for path in changed:
        texts[path] = read_head(path)
        result = parse(texts[path])
        if result is None:
            failures.append("%s: front matter missing or malformed" % path)
            continue
        parsed[path] = result

    facets_named = set()
    for path, (top, nested) in parsed.items():
        if top.get("type") != "Guidance":
            continue
        if "applies-to" not in top:
            failures.append("%s: no applies-to mapping" % path)
        applies = nested.get("applies-to", {})
        for key in ("facets", "steps"):
            if key in applies and inline_list(applies[key]) is None:
                failures.append("%s: applies-to %s must be an inline list on one line" % (path, key))
        for facet in inline_list(applies.get("facets", "[]")) or []:
            facets_named.add(facet)
            if facet not in facet_pages:
                failures.append("%s: facet '%s' has no concept page %s.md" % (path, facet, facet))
        for step in inline_list(applies.get("steps", "[]")) or []:
            if not STEP.match(step):
                failures.append("%s: step '%s' is not <step> or <origin>/<step>" % (path, step))
        status = top.get("status")
        if status not in ("draft", "stable", "deprecated"):
            failures.append("%s: status '%s' is not draft, stable or deprecated" % (path, status))
        for field in CONTEXT:
            if not top.get(field):
                failures.append("%s: missing or empty front-matter field '%s'" % (path, field))
        for found in item_ids(texts[path]):
            failures.append(
                "%s: names item id '%s' - record its origin on the item's finding artifact instead"
                % (path, found)
            )

    for path, (top, _) in parsed.items():
        stem = path.rsplit("/", 1)[-1][:-3]
        if top.get("type") != "Guidance" and stem not in facets_named:
            failures.append("%s: no type: Guidance and no entry names it as a facet" % path)

    return failures
