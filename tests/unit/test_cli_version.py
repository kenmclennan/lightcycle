import io
import unittest
from contextlib import redirect_stdout

from lightcycle import __version__
from lightcycle.cli import cmd_version


class TestCmdVersion(unittest.TestCase):
    def test_prints_lightcycle_version(self):
        out = io.StringIO()
        with redirect_stdout(out):
            rc = cmd_version([]) or 0
        self.assertEqual(rc, 0)
        self.assertEqual(out.getvalue().strip(), "lightcycle %s" % __version__)


if __name__ == "__main__":
    unittest.main()
