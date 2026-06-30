#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

# pytest, via uv (the dev venv). The engine itself ships zero runtime deps; pytest
# and pytest-bdd are dev/test tooling only. Pass args through, e.g.
#   bash tests/run.sh tests/unit     # the fast unit suite (no subprocess)
#   bash tests/run.sh -k claim       # a subset by name
uv run pytest "$@"
