import os
import tempfile

import pytest

from tests.support import hermetic_env
from tests.support.hermetic_env import REAL_HOME, RealHomeAccessError, expect_real_home_access


def test_apply_points_home_at_a_fresh_directory_distinct_from_the_real_home():
    home = hermetic_env.apply()

    assert os.environ["HOME"] == home
    assert home != REAL_HOME
    assert os.path.isdir(home)
    assert os.environ["LC_TEST_REAL_HOME"] == REAL_HOME


def test_apply_writes_a_global_gitconfig_holding_only_use_config_only():
    home = hermetic_env.apply()

    path = os.environ["GIT_CONFIG_GLOBAL"]
    assert os.path.dirname(path) == home
    with open(path) as handle:
        assert handle.read() == "[user]\n\tuseConfigOnly = true\n"
    assert os.environ["GIT_CONFIG_NOSYSTEM"] == "1"


def test_apply_removes_every_ambient_git_identity_variable(monkeypatch):
    names = [
        "GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_AUTHOR_DATE",
        "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL", "GIT_COMMITTER_DATE",
        "EMAIL", "GIT_CONFIG", "GIT_CONFIG_SYSTEM", "GIT_CONFIG_COUNT",
        "GIT_CONFIG_KEY_0", "GIT_CONFIG_VALUE_0", "GIT_CONFIG_KEY_3",
    ]
    for name in names:
        monkeypatch.setenv(name, "x")

    hermetic_env.apply()

    for name in names:
        assert name not in os.environ


def test_a_second_apply_returns_a_different_home():
    first = hermetic_env.apply()
    second = hermetic_env.apply()

    assert first != second
    assert not os.path.exists(first)


def test_guard_blocks_listing_and_reading_the_real_home_and_records_both():
    with expect_real_home_access() as absorbed:
        with pytest.raises(RealHomeAccessError):
            os.listdir(REAL_HOME)
        with pytest.raises(RealHomeAccessError):
            open(os.path.join(REAL_HOME, ".lc987-probe"))

    assert len(absorbed) == 2


def test_a_violation_swallowed_by_the_code_under_test_still_fails_end_test(monkeypatch):
    hermetic_env.begin_test()
    try:
        os.listdir(REAL_HOME)
    except Exception:
        pass

    with pytest.raises(AssertionError):
        hermetic_env.end_test()

    hermetic_env.begin_test()


def test_guard_allows_the_repo_root_and_temp_paths():
    root = os.path.join(os.path.dirname(__file__), "..", "..", "pyproject.toml")
    with open(root):
        pass

    path = tempfile.mkdtemp()
    os.listdir(path)


def test_guard_reports_only_the_non_allowed_child_of_the_real_home(monkeypatch):
    base = os.path.realpath(tempfile.mkdtemp())
    allowed = os.path.join(base, "allowed")
    other = os.path.join(base, "other")
    os.mkdir(allowed)
    os.mkdir(other)
    monkeypatch.setattr(hermetic_env, "REAL_HOME", base)
    monkeypatch.setattr(hermetic_env, "_allowed_roots", lambda: [os.path.realpath(allowed)])

    with expect_real_home_access() as absorbed:
        os.listdir(allowed)
        with pytest.raises(RealHomeAccessError):
            os.listdir(other)

    assert [path for _, path in absorbed] == [os.path.realpath(other)]


def test_guard_allows_a_sibling_workflows_checkout_but_not_another_sibling(monkeypatch, tmp_path):
    repo = tmp_path / "lightcycle" / ".worktrees" / "x"
    repo.mkdir(parents=True)
    (tmp_path / "lightcycle-workflows").mkdir()
    (tmp_path / "other-repo").mkdir()
    monkeypatch.setattr(hermetic_env, "_REPO_ROOT", str(repo))

    roots = hermetic_env._sibling_checkouts()

    assert roots == [str(tmp_path / "lightcycle-workflows")]


def test_sibling_checkouts_is_empty_when_no_workflows_checkout_exists(monkeypatch, tmp_path):
    repo = tmp_path / "lightcycle"
    repo.mkdir()
    monkeypatch.setattr(hermetic_env, "_REPO_ROOT", str(repo))

    assert hermetic_env._sibling_checkouts() == []
