import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_a_populated_global_gitconfig_and_author_variables_are_invisible_to_the_session():
    home = tempfile.mkdtemp()
    gitconfig = Path(home, ".gitconfig")
    gitconfig.write_text("[user]\n\tname = real\n\temail = real@real\n")
    env = dict(os.environ)
    env.pop("LC_TEST_REAL_HOME", None)
    env.update({
        "HOME": home,
        "GIT_CONFIG_GLOBAL": str(gitconfig),
        "GIT_AUTHOR_NAME": "real",
        "GIT_AUTHOR_EMAIL": "real@real",
        "EMAIL": "real@real",
    })

    result = subprocess.run(
        [
            sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-p", "no:xdist",
            "-o", "python_files=hermetic_probe.py", "tests/support/hermetic_probe.py",
        ],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )

    assert result.returncode == 0, result.stdout + result.stderr
