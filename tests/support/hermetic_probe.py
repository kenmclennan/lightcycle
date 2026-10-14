import subprocess
import tempfile


def _git(*args, cwd=None):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=30)


def test_no_identity_is_visible_and_commits_fail_without_one():
    assert _git("config", "--get", "user.name").returncode == 1

    repo = tempfile.mkdtemp()
    _git("init", "-q", cwd=repo)

    assert _git("commit", "--allow-empty", "-m", "x", cwd=repo).returncode != 0
    assert _git(
        "-c", "user.name=t", "-c", "user.email=t@t", "commit", "--allow-empty", "-m", "x", cwd=repo
    ).returncode == 0
