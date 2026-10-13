INDEX_PATH = "index.md"
CONVENTIONS_PATH = "CONVENTIONS.md"

COMMIT_MESSAGE = "chore: add the guidance repo skeleton"

INDEX_TEXT = """---
okf_version: "0.2"
---

# Guidance repo

The guidance lightcycle delivers to its agents, one entry per file. Read CONVENTIONS.md for the profile every entry follows.
"""

CONVENTIONS_TEXT = """# Conventions

This bundle follows the Open Knowledge Format (OKF) 0.2 with the lightcycle profile below.

## Entries

- An entry is one markdown file with front matter.
- `type: Guidance` marks an entry lightcycle may deliver to an agent.
- `applies-to` names the facets and steps an entry applies to.
- `covers:` marks an entry that stands in for others, listing what it covers.

## Status

- `status: stable` with a human `verified` record is the only state that is delivered.
- `status: draft` is never delivered.
- `status: deprecated` is retired and never delivered.

## Changes

Entries change by pull request only. Nothing is written to the default branch directly.
"""
