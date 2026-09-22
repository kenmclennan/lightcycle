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


def _inner_worker_count(outer_workers, cores):
    if not outer_workers or not outer_workers.isdigit() or int(outer_workers) < 1:
        return "auto"
    return str(max(1, cores // int(outer_workers)))


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


def test_tui_suite_passes_with_empty_home_and_lc_home():
    files = _tui_harness_test_files()
    assert files

    empty_home = tempfile.mkdtemp()
    env = dict(os.environ)
    env["HOME"] = empty_home
    env["LC_HOME"] = empty_home
    env.pop("LC_CONFIG", None)
    inner = _inner_worker_count(os.environ.get("PYTEST_XDIST_WORKER_COUNT"), os.cpu_count() or 1)

    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-n", inner, "--dist=loadgroup", *files],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
