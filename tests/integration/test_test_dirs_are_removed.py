import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

_LEAKING_TEST = "import tempfile\n\n\ndef test_makes_a_dir():\n    tempfile.mkdtemp()\n"


def test_a_suite_subset_leaves_nothing_in_tmpdir():
    with tempfile.TemporaryDirectory() as scratch, tempfile.TemporaryDirectory(dir="/tmp") as src:
        (Path(src) / "test_leaky.py").write_text(_LEAKING_TEST)
        env = {k: v for k, v in os.environ.items() if k != "PYTEST_XDIST_WORKER"}
        env["TMPDIR"] = scratch
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-p",
                "no:cacheprovider",
                "-p",
                "tests.conftest",
                "-n",
                "0",
                "-q",
                "--rootdir",
                str(REPO_ROOT),
                str(Path(src) / "test_leaky.py"),
            ],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=300,
        )
        leftover = sorted(os.listdir(scratch))
        assert result.returncode == 0, result.stdout + result.stderr
        assert leftover == []
