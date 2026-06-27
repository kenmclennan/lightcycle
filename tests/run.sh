#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

# Fast in-process unit suite over the pure core (no bd, no subprocess) - seconds.
echo "== unit (the_grid.core) =="
python3 -m unittest discover -s tests/unit -p 'test_*.py' -v

# CLI + store integration suites (shell out to tg/bd against a real embedded store) - slow.
echo "== integration (tg CLI + BdStore contract) =="
python3 -m unittest discover -s tests -p 'test_*.py' -v
