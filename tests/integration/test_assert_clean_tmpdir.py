import os
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "assert_clean_tmpdir.py"


def _run(tmp_path, *command):
    env = dict(os.environ)
    env["TMPDIR"] = str(tmp_path)
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--", *command],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_a_clean_command_exits_zero(tmp_path):
    assert _run(tmp_path, sys.executable, "-c", "pass").returncode == 0


def test_a_planted_leak_exits_non_zero_naming_one_leftover(tmp_path):
    code = "import tempfile, os; tempfile.mkdtemp(dir=os.environ['TMPDIR'])"
    result = _run(tmp_path, sys.executable, "-c", code)
    assert result.returncode != 0
    assert result.stderr.count("leftover in TMPDIR:") == 1


def test_a_failing_clean_command_exits_non_zero(tmp_path):
    assert _run(tmp_path, sys.executable, "-c", "raise SystemExit(3)").returncode != 0
