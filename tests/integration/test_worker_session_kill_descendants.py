import os
import stat
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

import lightcycle.adapters.worker_session as ws

STAND_IN = """#!/bin/sh
trap '' TERM
sleep 300 &
echo $! > "$LC_TEST_DIR/sleep.pid"
echo $$ > "$LC_TEST_DIR/claude.pid"
while true; do sleep 1; done
"""

DEADLINE = 30.0


def _alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    out = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True,
                         timeout=10)
    return bool(out.stdout.strip()) and not out.stdout.strip().startswith("Z")


def _read_pid(path):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            with open(path) as f:
                text = f.read().strip()
            if text:
                return int(text)
        except (FileNotFoundError, ValueError):
            pass
        time.sleep(0.05)
    raise AssertionError("no pid file at %s" % path)


class TestSessionKillDescendants(unittest.TestCase):
    def _run_session(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        d = tmp.name
        script = os.path.join(d, "claude")
        with open(script, "w") as f:
            f.write(STAND_IN)
        os.chmod(script, os.stat(script).st_mode | stat.S_IXUSR)
        env = dict(os.environ, PATH=d + os.pathsep + os.environ["PATH"], LC_TEST_DIR=d)
        seen = {}
        real_snapshot = ws.descendant_pids

        def snapshot(pid):
            seen["claude_pid"] = pid
            seen["same_group"] = os.getpgid(pid) == os.getpgid(0)
            seen["descendants"] = real_snapshot(pid)
            return seen["descendants"]

        with patch.object(ws, "EXIT_GRACE_SECONDS", 1), \
                patch.object(ws, "descendant_pids", snapshot):
            ws.run(d, d, "coder", "opus", "sys", 1, open_step=lambda: False, env=env)
        seen["sleep_pid"] = _read_pid(os.path.join(d, "sleep.pid"))
        return seen

    def test_no_descendant_survives_the_sigkill_fallback(self):
        seen = self._run_session()
        self.assertIn(seen["sleep_pid"], seen["descendants"])
        deadline = time.monotonic() + DEADLINE
        survivors = seen["descendants"]
        while time.monotonic() < deadline:
            survivors = [p for p in seen["descendants"] if _alive(p)]
            if not survivors:
                break
            time.sleep(0.1)
        self.assertEqual(survivors, [])

    def test_claude_stays_in_the_workers_process_group(self):
        seen = self._run_session()
        self.assertTrue(seen["same_group"])
