import ast
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _imports_tui_harness(source):
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name == "tests.support.tui_harness" for alias in node.names):
                return True
        elif isinstance(node, ast.ImportFrom):
            if node.module == "tests.support.tui_harness":
                return True
            if node.module == "tests.support" and any(alias.name == "tui_harness" for alias in node.names):
                return True
    return False


def _positive_int(value):
    if value and value.isdigit() and int(value) >= 1:
        return int(value)
    return None


def _inner_worker_count(outer_workers, cores, max_agents=None):
    outer = _positive_int(outer_workers)
    pool = _positive_int(max_agents)
    if pool:
        return str(max(1, cores // pool // (outer or 1)))
    if not outer:
        return "auto"
    return str(max(1, cores // outer))


def _tui_harness_test_files():
    files = []
    for base in ("tests/unit", "tests/feature"):
        for path in sorted((REPO_ROOT / base).rglob("test_*.py")):
            if _imports_tui_harness(path.read_text()):
                files.append(str(path.relative_to(REPO_ROOT)))
    return files


@pytest.mark.parametrize("source,expected", [
    ("import tests.support.tui_harness\n", True),
    ("from tests.support.tui_harness import make_test_container\n", True),
    ("from tests.support import tui_harness\n", True),
    ("from tests.support import fake_fs\n", False),
])
def test_imports_tui_harness_recognizes_every_import_shape(source, expected):
    assert _imports_tui_harness(source) == expected


def test_tui_harness_test_files_discovers_the_real_current_file_set():
    files = _tui_harness_test_files()

    assert "tests/unit/test_tui_app.py" in files
    assert "tests/feature/test_the_node_hub.py" in files
    assert "tests/unit/test_fake_store.py" not in files


@pytest.mark.parametrize("outer,cores,expected", [
    (None, 8, "auto"),
    ("", 8, "auto"),
    ("junk", 8, "auto"),
    ("4", 8, "2"),
    ("8", 8, "1"),
    ("16", 8, "1"),
])
def test_inner_worker_count_shares_cores_with_the_outer_run(outer, cores, expected):
    assert _inner_worker_count(outer, cores) == expected


@pytest.mark.parametrize("outer,cores,max_agents,expected", [
    ("1", 8, "5", "1"),
    (None, 8, "5", "1"),
    ("1", 16, "4", "4"),
    ("2", 16, "4", "2"),
    ("4", 16, "2", "2"),
    ("1", 8, "16", "1"),
    ("4", 8, None, "2"),
    ("4", 8, "", "2"),
    ("4", 8, "0", "2"),
    ("4", 8, "junk", "2"),
    (None, 8, "junk", "auto"),
])
def test_inner_worker_count_shares_cores_with_the_pool(outer, cores, max_agents, expected):
    assert _inner_worker_count(outer, cores, max_agents) == expected


_SMOKE_STATE = "hub#workflow"


def _empty_home_env(empty_home):
    env = dict(os.environ)
    env["HOME"] = empty_home
    env["LC_HOME"] = empty_home
    env.pop("LC_CONFIG", None)
    return env


def _run_under_empty_home(args):
    empty_home = tempfile.mkdtemp()
    result = subprocess.run(
        [sys.executable, *args],
        cwd=str(REPO_ROOT),
        env=_empty_home_env(empty_home),
        capture_output=True,
        text=True,
        timeout=300,
    )
    return result, sorted(os.listdir(empty_home))


def _home_clean(result, leftovers):
    return result.returncode == 0 and not leftovers


def test_registered_screen_state_renders_with_empty_home_and_lc_home():
    result, leftovers = _run_under_empty_home(["-m", "tests.support.screen_render", _SMOKE_STATE])

    assert _home_clean(result, leftovers), result.stdout + result.stderr + repr(leftovers)
    assert result.stdout.strip()


def test_empty_home_smoke_fails_when_the_harness_reads_a_home_dependent_path():
    code = (
        "import os, pathlib\n"
        "pathlib.Path(os.path.expanduser('~'), 'harness-state').write_text('x')\n"
    )

    result, leftovers = _run_under_empty_home(["-c", code])

    assert not _home_clean(result, leftovers)
    assert leftovers == ["harness-state"]
