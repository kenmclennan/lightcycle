"""Architecture guardrail: the domain speaks no bd wire-format.

The bead -> domain mapping lives only in adapters/bead.py. If bd's shape leaks
back into the domain, this fails. retro.py is the one known remaining leak (its
bd-history read); it drops off the allow-list when Retro/Signal lands (the
feedback part-2 batch) - GRID-014 the-grid-ci9.
"""
import pathlib
import unittest

DOMAIN = pathlib.Path(__file__).resolve().parents[2] / "the_grid" / "domain"

# Unambiguous bd wire-format markers - these only ever appear in the bd adapter.
BD_MARKERS = ('"Issue"', "issue_type", "close_reason", "dependency_count")
ALLOW = {"retro.py"}


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
