import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_a_suite_subset_leaves_no_lc_test_entries_in_tmpdir():
    with tempfile.TemporaryDirectory() as scratch:
        env = {k: v for k, v in os.environ.items() if k != "PYTEST_XDIST_WORKER"}
        env["TMPDIR"] = scratch
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-p",
                "no:cacheprovider",
                "-n",
                "0",
                "-q",
                "tests/unit/test_field_owner.py",
            ],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=300,
        )
        leftover = sorted(n for n in os.listdir(scratch) if n.startswith("lc-test-"))
        assert result.returncode == 0, result.stdout + result.stderr
        assert leftover == []
