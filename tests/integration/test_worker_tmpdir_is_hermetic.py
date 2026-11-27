import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from lightcycle.adapters import step_scratch

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_hermetic_tests_pass_with_tmpdir_set_to_a_worker_scratch_folder():
    with tempfile.TemporaryDirectory() as root:
        scratch = step_scratch.create_scratch(root, "abcd1234")
        try:
            run = subprocess.run(
                [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-n", "0", "-q",
                 "tests/unit/test_hermetic_env.py", "tests/unit/test_config.py"],
                cwd=REPO_ROOT, env=dict(os.environ, TMPDIR=scratch),
                capture_output=True, text=True, timeout=300,
            )
        finally:
            shutil.rmtree(step_scratch.scratch_root(root), ignore_errors=True)
        assert run.returncode == 0, run.stdout + run.stderr
