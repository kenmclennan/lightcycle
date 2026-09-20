#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

# pytest, via uv (the dev venv). The engine itself ships zero runtime deps; pytest
# and pytest-bdd are dev/test tooling only. Pass args through, e.g.
#   bash tests/run.sh tests/unit     # the fast unit suite (no subprocess)
#   bash tests/run.sh -k claim       # a subset by name
workers=auto
if [ -n "${LC_MAX_AGENTS:-}" ] && [ "$LC_MAX_AGENTS" -gt 0 ] 2>/dev/null; then
  workers=$(( $(getconf _NPROCESSORS_ONLN) / LC_MAX_AGENTS ))
  [ "$workers" -ge 1 ] || workers=1
fi
uv run pytest -n "$workers" --dist=loadgroup "$@"
