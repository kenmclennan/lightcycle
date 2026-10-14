import unittest
from pathlib import Path
from types import SimpleNamespace

from lightcycle.application.workflows.bundle_check import check_bundle_references

_LIBRARY = Path(__file__).resolve().parents[1] / "support" / "library"


class TestBundleDeclaringTheRetiredHook(unittest.TestCase):
    def test_a_bundle_still_declaring_review_bot_allowlist_raises_no_problem(self):
        text = (_LIBRARY / "workflows" / "spec-driven.md").read_text()
        self.assertIn("review_bot_allowlist", text)
        steps = {p.stem: p.read_text() for p in (_LIBRARY / "steps").glob("*.md")}
        bundle = SimpleNamespace(steps=steps, workflows={"spec-driven": text})

        problems = check_bundle_references(bundle)

        self.assertEqual(
            [m for ms in problems.values() for m in ms if "review_bot_allowlist" in m], [])
