import glob
import os
import unittest
from unittest.mock import patch

from lightcycle import __version__
from lightcycle.adapters.tui.app import LightcycleApp
from lightcycle.container import Container
from tests.support.tui_harness import HermeticTuiConfig, make_test_container


def _render_priority_rows(row_key, step, filler):
    raise KeyError("no such row: %s" % row_key)


class _Step:
    id = "REC-319.35"


class TuiCrashReportTest(unittest.TestCase):
    def setUp(self):
        patcher = patch("lightcycle.adapters.tui.app.CRASH_PACKAGE_DIR", os.path.dirname(os.path.abspath(__file__)) + os.sep)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _crash(self):
        container = Container(config=HermeticTuiConfig())
        app = LightcycleApp(container)
        filler = ["BOARD-WIDE-LOCAL"] * 3
        try:
            _render_priority_rows("REC-319.35", _Step(), filler)
        except KeyError:
            app._fatal_error()
        return container, app

    def _report(self, app):
        return [str(r) for r in app._exit_renderables]

    def test_a_crash_prints_a_short_report_not_the_traceback(self):
        _, app = self._crash()
        lines = self._report(app)
        self.assertLessEqual(len(lines), 12)
        self.assertIn("KeyError", lines[0])
        self.assertIn("no such row: REC-319.35", lines[0])
        self.assertTrue(any("test_tui_crash_report.py" in l and "in _render_priority_rows" in l for l in lines))
        self.assertTrue(any("row_key=REC-319.35" in l and "step=REC-319.35" in l for l in lines))
        self.assertNotIn("BOARD-WIDE-LOCAL", "\n".join(lines))

    def test_the_full_traceback_with_locals_goes_to_a_crash_log(self):
        container, app = self._crash()
        logs = glob.glob(os.path.join(container.fs.ensure_logs_dir(), "tui-crash-*.log"))
        self.assertEqual(len(logs), 1)
        self.assertTrue(any(logs[0] in l for l in self._report(app)))
        text = open(logs[0]).read()
        self.assertIn(__version__, text.splitlines()[0])
        self.assertIn("crashed at", text.splitlines()[1])
        self.assertIn("Traceback", text)
        self.assertIn("BOARD-WIDE-LOCAL", text)
        self.assertIn("_render_priority_rows", text)

    def test_the_app_still_exits_non_zero_after_a_crash(self):
        _, app = self._crash()
        self.assertEqual(app._return_code, None)
        try:
            _render_priority_rows("r", _Step(), [])
        except KeyError as err:
            app._handle_exception(err)
        self.assertEqual(app._return_code, 1)

    def test_an_unwritable_logs_dir_still_yields_a_report(self):
        container = make_test_container()
        app = LightcycleApp(container)
        with patch.object(type(container.fs), "ensure_logs_dir", side_effect=OSError("read-only")):
            try:
                _render_priority_rows("r", _Step(), [])
            except KeyError:
                app._fatal_error()
        lines = self._report(app)
        self.assertIn("KeyError", lines[0])
        self.assertTrue(any("crash log not written" in l for l in lines))
