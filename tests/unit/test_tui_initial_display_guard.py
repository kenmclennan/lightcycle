import unittest
from pathlib import Path

from tests.support.tui_display_guard import find_violations

_TUI_ROOT = Path(__file__).resolve().parents[2] / "lightcycle" / "adapters" / "tui"


class TestTuiInitialDisplayGuard(unittest.TestCase):
    def test_no_toggled_widget_depends_solely_on_a_deferred_callback(self):
        sources = {str(path): path.read_text() for path in sorted(_TUI_ROOT.rglob("*.py"))}
        violations, unresolved = find_violations(sources)
        self.assertEqual(violations, [])
        self.assertEqual(unresolved, [])
