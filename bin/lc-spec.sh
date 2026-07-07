#!/usr/bin/env bash
# Render a spec (or list specs) with glow for in-situ review.
set -euo pipefail
root="${LC_ROOT_OVERRIDE:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"

if [[ $# -eq 0 ]]; then
  echo "specs:"
  ls -1 "$root/specs"/*.md 2>/dev/null | sed "s#$root/specs/##; s#\.md##"
  echo ""
  echo "usage: lc-spec.sh <spec-id>"
  exit 0
fi

id="$1"
spec="$root/specs/$id.md"
[[ -f "$spec" ]] || spec="$root/specs/$id"   # allow passing full filename
[[ -f "$spec" ]] || { echo "no such spec: $id" >&2; exit 1; }

if command -v glow >/dev/null 2>&1; then
  glow -p "$spec"
else
  echo "glow not installed (brew install glow); showing raw:" >&2
  cat "$spec"
fi
