import pathlib
import re
import unittest

from lightcycle.cli_commands import flags_by_verb
from lightcycle.config import _SEED_KEYS

REPO = pathlib.Path(__file__).resolve().parents[2]
PKG = REPO / "lightcycle"
CORPUS = [REPO / "CLAUDE.md"] + sorted((REPO / "docs").glob("*.md"))

PATHISH = re.compile(r"`([A-Za-z0-9_./-]+\.(?:py|md|sh|toml|json|yml|yaml))(?::[0-9,\-]+)?`")
LC_CALL = re.compile(r"`lc ([a-z][a-z-]*)((?: [^`]*)?)`")

CONFIG_DOC = REPO / "docs" / "installation-and-config.md"
CONFIG_TABLE_ROW = re.compile(r"^\|([^|]*)\|", re.MULTILINE)
PRICE_FAMILY = re.compile(
    r"^price-(sonnet|opus|haiku)-(input|output|cache-write|cache-read)-per-mtok$"
)
PRICE_FAMILY_PLACEHOLDER = "price-<model>-<kind>-per-mtok"

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


class TestDocsDocumentEveryConfigKey(unittest.TestCase):
    def test_every_seed_key_has_a_config_table_row(self):
        text = CONFIG_DOC.read_text()
        section = text.split("\n## Config\n", 1)[1].split("\n## ", 1)[0]
        documented = set()
        for row in CONFIG_TABLE_ROW.finditer(section):
            documented.update(re.findall(r"`([a-z0-9<>-]+)`", row.group(1)))

        seed_names = {k for k, _ in _SEED_KEYS}
        price_keys = {k for k in seed_names if PRICE_FAMILY.match(k)}
        individual = seed_names - price_keys

        missing = sorted(individual - documented)
        if price_keys and PRICE_FAMILY_PLACEHOLDER not in documented:
            missing.append(PRICE_FAMILY_PLACEHOLDER)

        self.assertEqual(
            missing,
            [],
            "docs/installation-and-config.md's Config table omits: %s" % missing,
        )
