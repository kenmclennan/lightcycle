import pathlib
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
DOMAIN = REPO_ROOT / "lightcycle" / "domain"
LIGHTCYCLE = REPO_ROOT / "lightcycle"

BD_MARKERS = ('"Issue"', "issue_type", "close_reason", "dependency_count")
ALLOW = set()


class TestDomainSpeaksNoBead(unittest.TestCase):
    def test_no_bd_wire_format_in_domain(self):
        offenders = []
        for path in sorted(DOMAIN.rglob("*.py")):
            if path.name in ALLOW:
                continue
            text = path.read_text()
            for marker in BD_MARKERS:
                if marker in text:
                    offenders.append("%s: %s" % (path.relative_to(DOMAIN), marker))
        self.assertEqual(offenders, [], "bd wire-format leaked into the domain: %s" % offenders)


class TestStoreFilenameHasOneDefinition(unittest.TestCase):
    def test_store_db_literal_appears_once(self):
        sites = []
        for path in sorted(LIGHTCYCLE.rglob("*.py")):
            for lineno, line in enumerate(path.read_text().splitlines(), start=1):
                if '"store.db"' in line:
                    sites.append("%s:%d" % (path.relative_to(LIGHTCYCLE), lineno))
        self.assertEqual(len(sites), 1, "store.db respelled outside its constant: %s" % sites)
        self.assertEqual(sites[0].split(":")[0], "adapters/fsio.py")


if __name__ == "__main__":
    unittest.main()
