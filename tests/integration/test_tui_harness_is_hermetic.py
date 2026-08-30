import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _tui_harness_test_files():
    files = []
    for base in ("tests/unit", "tests/feature"):
        for path in sorted((REPO_ROOT / base).rglob("test_*.py")):
            if "tests.support.tui_harness" in path.read_text():
                files.append(str(path.relative_to(REPO_ROOT)))
    return files


def test_tui_suite_passes_with_empty_home_and_lc_home():
    files = _tui_harness_test_files()
    assert files

    empty_home = tempfile.mkdtemp()
    env = dict(os.environ)
    env["HOME"] = empty_home
    env["LC_HOME"] = empty_home
    env.pop("LC_CONFIG", None)

    result = subprocess.run(
        [sys.executable, "-m", "pytest", *files],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
