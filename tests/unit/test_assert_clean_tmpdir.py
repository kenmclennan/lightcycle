import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "assert_clean_tmpdir.py"

_spec = importlib.util.spec_from_file_location("assert_clean_tmpdir", SCRIPT)
gate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gate)


def test_leftovers_ignores_tool_owned_entries(tmp_path):
    (tmp_path / "ordinary").mkdir()
    (tmp_path / "uv-0123abcd.lock").write_text("")
    (tmp_path / "pytest-of-x").mkdir()
    assert gate.leftovers(str(tmp_path)) == ["ordinary"]


def test_leftovers_reports_a_non_empty_pytest_of_directory(tmp_path):
    (tmp_path / "pytest-of-x" / "pytest-0").mkdir(parents=True)
    assert gate.leftovers(str(tmp_path)) == ["pytest-of-x"]
