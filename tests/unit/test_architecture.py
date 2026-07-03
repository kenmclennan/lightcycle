import pathlib
import unittest

DOMAIN = pathlib.Path(__file__).resolve().parents[2] / "the_grid" / "domain"

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


if __name__ == "__main__":
    unittest.main()
