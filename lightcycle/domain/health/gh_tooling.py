import re
from dataclasses import dataclass
from typing import Optional

from lightcycle.domain.health.problem import Problem

_VERSION_RE = re.compile(r"gh version (\d+)\.(\d+)")


@dataclass(frozen=True)
class GhTooling:
    version_text: Optional[str] = None


def parse_gh_version(text):
    if not text:
        return None
    first = text.strip().split("\n")[0]
    m = _VERSION_RE.match(first.strip())
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)))


def gh_tooling_problems(tooling):
    if parse_gh_version(tooling.version_text) is None:
        return [Problem(
            "github", "gh is missing or did not report a version",
            fix="install the GitHub CLI (https://cli.github.com)",
        )]
    return []
