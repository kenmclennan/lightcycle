#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

# Fast in-process unit suite over the pure core (no bd, no subprocess) - seconds.
echo "== unit (grid.core) =="
python3 -m unittest discover -s tests/unit -p 'test_*.py' -v

# CLI integration suite (shells out to tg/bd against a real embedded store) - slow.
echo "== integration (tg CLI) =="
python3 -m unittest discover -s tests -p 'test_tg.py' -v
