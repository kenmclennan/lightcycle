import os
import re
import stat
import tempfile
import unittest
from unittest.mock import patch

from lightcycle.adapters.run_log import run_logged


class TestRunLoggedDuration(unittest.TestCase):
    def test_the_footer_duration_does_not_read_the_wall_clock_a_second_time(self):
        root = tempfile.mkdtemp()
        script = os.path.join(root, "ok.sh")
        with open(script, "w") as f:
            f.write("#!/bin/sh\nexit 0\n")
        os.chmod(script, os.stat(script).st_mode | stat.S_IXUSR)
        log_path = os.path.join(root, "script-1.log")

        with patch("lightcycle.adapters.run_log.time.time", side_effect=[1_700_000_000.0]):
            run = run_logged(None, "other", log_path, script, root, dict(os.environ), None, 30)

        self.assertEqual(run.exit_code, 0)
        with open(log_path) as f:
            text = f.read()
        match = re.search(r"exit 0 \((\d+\.\d)s\)", text)
        self.assertIsNotNone(match, text)
        self.assertGreaterEqual(float(match.group(1)), 0.0)
        self.assertIn("started: 2023-11-1", text)


if __name__ == "__main__":
    unittest.main()
