import re
from dataclasses import dataclass
from typing import Optional

from lightcycle.domain.health.problem import Problem

GH_MINIMUM = (2, 90)
GH_STACK_EXTENSION = "github/gh-stack"

_VERSION_RE = re.compile(r"gh version (\d+)\.(\d+)")


@dataclass(frozen=True)
class GhTooling:
    version_text: Optional[str] = None
    extensions_text: Optional[str] = None


def parse_gh_version(text):
    if not text:
        return None
    first = text.strip().split("\n")[0]
    m = _VERSION_RE.match(first.strip())
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)))


def parse_extensions(text):
    found = []
    for line in (text or "").splitlines():
        columns = line.split("\t")
        if len(columns) >= 2 and columns[1].strip():
            found.append(columns[1].strip())
    return found


def gh_tooling_problems(tooling):
    version = parse_gh_version(tooling.version_text)
    if version is None:
        return [Problem(
            "github", "gh is missing or did not report a version; stacked delivery needs gh %d.%d or later"
            % GH_MINIMUM,
            fix="install the GitHub CLI (https://cli.github.com)",
        )]
    problems = []
    if version < GH_MINIMUM:
        problems.append(Problem(
            "github", "gh %d.%d is older than the %d.%d stacked delivery needs"
            % (version + GH_MINIMUM),
            fix="upgrade the GitHub CLI",
        ))
    if tooling.extensions_text is None:
        problems.append(Problem(
            "github", "gh extension list could not be read, so %s was not checked" % GH_STACK_EXTENSION,
            fix="run `gh extension list` and fix the error it reports",
        ))
    elif GH_STACK_EXTENSION not in parse_extensions(tooling.extensions_text):
        problems.append(Problem(
            "github", "the %s extension is not installed; stacked delivery falls back to one PR per item"
            % GH_STACK_EXTENSION,
            fix="gh extension install %s" % GH_STACK_EXTENSION,
        ))
    return problems
