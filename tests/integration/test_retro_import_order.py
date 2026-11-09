import subprocess
import sys
import unittest


def _imports_cleanly(first, second):
    code = "import %s\nimport %s\n" % (first, second)
    return subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=60
    )


class TestRetroImportOrder(unittest.TestCase):
    def test_retro_then_retro_scope(self):
        result = _imports_cleanly(
            "lightcycle.application.feedback.retro", "lightcycle.application.feedback.retro_scope"
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_retro_scope_then_retro(self):
        result = _imports_cleanly(
            "lightcycle.application.feedback.retro_scope", "lightcycle.application.feedback.retro"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
