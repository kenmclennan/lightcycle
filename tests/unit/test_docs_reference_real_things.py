import pathlib
import re
import unittest

from lightcycle.cli_commands import flags_by_verb

REPO = pathlib.Path(__file__).resolve().parents[2]
PKG = REPO / "lightcycle"
CORPUS = [REPO / "CLAUDE.md"] + sorted((REPO / "docs").glob("*.md"))

PATHISH = re.compile(r"`([A-Za-z0-9_./-]+\.(?:py|md|sh|toml|json|yml|yaml))(?::[0-9,\-]+)?`")
LC_CALL = re.compile(r"`lc ([a-z][a-z-]*)((?: [^`]*)?)`")

ELSEWHERE = {
    "source.toml",
    ".github/workflows/simulate.yml",
    "snake_case.py",
    "kebab-case.md",
    "package.json",
    "CLAUDE.md",
    "README.md",
}
NOT_A_COMMAND = {"plan-add"}


class TestDocsNameThingsThatExist(unittest.TestCase):
    def test_every_path_named_in_the_docs_resolves(self):
        missing = []
        for doc in CORPUS:
            for m in PATHISH.finditer(doc.read_text()):
                ref = m.group(1)
                if ref in ELSEWHERE or ref.startswith(("~", "http", "WORKSPACE/")):
                    continue
                if (REPO / ref).exists() or (PKG / ref).exists():
                    continue
                if "/" not in ref and (any(REPO.rglob(ref)) or any(PKG.rglob(ref))):
                    continue
                missing.append("%s: %s" % (doc.relative_to(REPO), ref))
        self.assertEqual(missing, [], "docs name files that do not exist: %s" % missing)


class TestDocsNameCommandsThatExist(unittest.TestCase):
    def test_every_lc_invocation_in_the_docs_is_a_real_command(self):
        surface = flags_by_verb()
        bad = []
        for doc in CORPUS:
            for m in LC_CALL.finditer(doc.read_text()):
                verb, rest = m.group(1), m.group(2)
                if verb in NOT_A_COMMAND:
                    continue
                if verb not in surface:
                    bad.append("%s: lc %s" % (doc.relative_to(REPO), verb))
                    continue
                for flag in re.findall(r"--([a-z][a-z-]*)", rest):
                    if flag not in surface[verb]:
                        bad.append("%s: lc %s --%s" % (doc.relative_to(REPO), verb, flag))
        self.assertEqual(bad, [], "docs name lc commands or flags that do not exist: %s" % bad)
