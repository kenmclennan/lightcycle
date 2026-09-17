import ast
import pathlib
import tempfile
import unittest

from tests.support.baseline_counts import grown_entries, parse_counts

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
LIGHTCYCLE = REPO_ROOT / "lightcycle"
ADAPTERS = LIGHTCYCLE / "adapters"
CONFIG = LIGHTCYCLE / "config.py"
TESTS_UNIT = REPO_ROOT / "tests" / "unit"
BASELINES = pathlib.Path(__file__).resolve().parent / "baselines"

SUBPROCESS_METHODS = {"run", "Popen", "call", "check_call", "check_output"}


def _paths(root, exclude_dirs=(), exclude_files=()):
    paths = []
    for path in sorted(root.rglob("*.py")):
        if any(exclude_dir in path.parents for exclude_dir in exclude_dirs):
            continue
        if path in exclude_files:
            continue
        paths.append(path)
    return paths


def _is_call_to(node, func_name, attr_owner=None):
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if attr_owner is None:
        return isinstance(func, ast.Name) and func.id == func_name
    return (
        isinstance(func, ast.Attribute) and func.attr == func_name
        and isinstance(func.value, ast.Name) and func.value.id == attr_owner
    )


def scan_os_environ(root, exclude_dirs=(), exclude_files=()):
    offenders = []
    for path in _paths(root, exclude_dirs, exclude_files):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "environ":
                if isinstance(node.value, ast.Name) and node.value.id == "os":
                    offenders.append("%s:%d" % (path.relative_to(root), node.lineno))
    return offenders


def _call_count_scan(root, matcher, exclude_dirs=(), exclude_files=()):
    counts = {}
    for path in _paths(root, exclude_dirs, exclude_files):
        tree = ast.parse(path.read_text(), filename=str(path))
        offenders = sum(1 for node in ast.walk(tree) if matcher(node))
        if offenders:
            counts[str(path.relative_to(root))] = offenders
    return counts


def scan_open_calls(root, exclude_dirs=(), exclude_files=()):
    return _call_count_scan(
        root, lambda n: _is_call_to(n, "open"), exclude_dirs, exclude_files
    )


def scan_os_makedirs_calls(root, exclude_dirs=(), exclude_files=()):
    return _call_count_scan(
        root, lambda n: _is_call_to(n, "makedirs", attr_owner="os"), exclude_dirs, exclude_files
    )


def scan_time_sleep_calls(root, exclude_dirs=(), exclude_files=()):
    return _call_count_scan(
        root, lambda n: _is_call_to(n, "sleep", attr_owner="time"), exclude_dirs, exclude_files
    )


def scan_os_exit_calls(root, exclude_dirs=(), exclude_files=()):
    return _call_count_scan(
        root, lambda n: _is_call_to(n, "_exit", attr_owner="os"), exclude_dirs, exclude_files
    )


def scan_io_capable_pathlib_imports(root, exclude_dirs=(), exclude_files=()):
    counts = {}
    for path in _paths(root, exclude_dirs, exclude_files):
        tree = ast.parse(path.read_text(), filename=str(path))
        offenders = 0
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                offenders += sum(1 for alias in node.names if alias.name == "pathlib")
            elif isinstance(node, ast.ImportFrom) and node.module == "pathlib":
                offenders += sum(
                    1 for alias in node.names if not alias.name.startswith("Pure")
                )
        if offenders:
            counts[str(path.relative_to(root))] = offenders
    return counts


def scan_import_ast(root, exclude_dirs=(), exclude_files=()):
    counts = {}
    for path in _paths(root, exclude_dirs, exclude_files):
        tree = ast.parse(path.read_text(), filename=str(path))
        offenders = sum(
            1 for node in ast.walk(tree) if isinstance(node, ast.Import)
            for alias in node.names if alias.name == "ast"
        )
        if offenders:
            counts[str(path.relative_to(root))] = offenders
    return counts


def scan_unmocked_subprocess_calls(root, exclude_dirs=(), exclude_files=()):
    offenders = []
    for path in _paths(root, exclude_dirs, exclude_files):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr not in SUBPROCESS_METHODS:
                continue
            if isinstance(node.func.value, ast.Name) and node.func.value.id == "subprocess":
                offenders.append("%s:%d" % (path.relative_to(root), node.lineno))
    return offenders


class TestOsEnviron(unittest.TestCase):
    def test_flags_os_environ_access(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "thing.py").write_text("import os\nos.environ.get('X')\n")
            self.assertEqual(scan_os_environ(root), ["thing.py:2"])

    def test_does_not_flag_a_file_with_no_os_environ_access(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "thing.py").write_text("import os\nos.getcwd()\n")
            self.assertEqual(scan_os_environ(root), [])

    def test_no_os_environ_access_outside_config_py(self):
        offenders = scan_os_environ(LIGHTCYCLE, exclude_files=(CONFIG,))
        self.assertEqual(offenders, [], "os.environ accessed outside config.py: %s" % offenders)


class TestOpenCalls(unittest.TestCase):
    BASELINE = BASELINES / "forbidden_open.txt"

    def test_flags_a_bare_open_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "thing.py").write_text("open('x')\n")
            self.assertEqual(scan_open_calls(root), {"thing.py": 1})

    def test_does_not_flag_a_file_with_no_open_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "thing.py").write_text("x = 1\n")
            self.assertEqual(scan_open_calls(root), {})

    def test_baseline_has_not_grown(self):
        before = parse_counts(self.BASELINE.read_text())
        after = scan_open_calls(LIGHTCYCLE, exclude_dirs=(ADAPTERS,), exclude_files=(CONFIG,))
        after_keyed = {"lightcycle/%s" % k: v for k, v in after.items()}
        grown = grown_entries(before, after_keyed)
        self.assertEqual(grown, {}, "open() calls outside adapters/ grew: %s" % grown)

    def test_a_baselined_file_with_one_more_offender_fails(self):
        before = {"x.py": 1}
        after = {"x.py": 2}
        self.assertEqual(grown_entries(before, after), {"x.py": (1, 2)})


class TestOsMakedirsCalls(unittest.TestCase):
    BASELINE = BASELINES / "forbidden_os_makedirs.txt"

    def test_flags_an_os_makedirs_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "thing.py").write_text("import os\nos.makedirs('x')\n")
            self.assertEqual(scan_os_makedirs_calls(root), {"thing.py": 1})

    def test_does_not_flag_a_file_with_no_os_makedirs_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "thing.py").write_text("import os\nos.getcwd()\n")
            self.assertEqual(scan_os_makedirs_calls(root), {})

    def test_baseline_has_not_grown(self):
        before = parse_counts(self.BASELINE.read_text())
        after = scan_os_makedirs_calls(
            LIGHTCYCLE, exclude_dirs=(ADAPTERS,), exclude_files=(CONFIG,)
        )
        after_keyed = {"lightcycle/%s" % k: v for k, v in after.items()}
        grown = grown_entries(before, after_keyed)
        self.assertEqual(grown, {}, "os.makedirs() calls outside adapters/ grew: %s" % grown)

    def test_a_baselined_file_with_one_more_offender_fails(self):
        before = {"x.py": 1}
        after = {"x.py": 2}
        self.assertEqual(grown_entries(before, after), {"x.py": (1, 2)})


class TestTimeSleepCalls(unittest.TestCase):
    BASELINE = BASELINES / "forbidden_time_sleep.txt"

    def test_flags_a_time_sleep_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "thing.py").write_text("import time\ntime.sleep(1)\n")
            self.assertEqual(scan_time_sleep_calls(root), {"thing.py": 1})

    def test_does_not_flag_a_file_with_no_time_sleep_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "thing.py").write_text("import time\ntime.monotonic()\n")
            self.assertEqual(scan_time_sleep_calls(root), {})

    def test_baseline_has_not_grown(self):
        before = parse_counts(self.BASELINE.read_text())
        after = scan_time_sleep_calls(
            LIGHTCYCLE, exclude_dirs=(ADAPTERS,), exclude_files=(CONFIG,)
        )
        after_keyed = {"lightcycle/%s" % k: v for k, v in after.items()}
        grown = grown_entries(before, after_keyed)
        self.assertEqual(grown, {}, "time.sleep() calls outside adapters/ grew: %s" % grown)

    def test_a_baselined_file_with_one_more_offender_fails(self):
        before = {"x.py": 1}
        after = {"x.py": 2}
        self.assertEqual(grown_entries(before, after), {"x.py": (1, 2)})


class TestIoCapablePathlibImports(unittest.TestCase):
    BASELINE = BASELINES / "forbidden_pathlib.txt"

    def test_flags_a_path_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "thing.py").write_text("from pathlib import Path\n")
            self.assertEqual(scan_io_capable_pathlib_imports(root), {"thing.py": 1})

    def test_does_not_flag_a_pure_path_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "thing.py").write_text("from pathlib import PurePosixPath\n")
            self.assertEqual(scan_io_capable_pathlib_imports(root), {})

    def test_baseline_has_not_grown(self):
        before = parse_counts(self.BASELINE.read_text())
        after = scan_io_capable_pathlib_imports(
            LIGHTCYCLE, exclude_dirs=(ADAPTERS,), exclude_files=(CONFIG,)
        )
        after_keyed = {"lightcycle/%s" % k: v for k, v in after.items()}
        grown = grown_entries(before, after_keyed)
        self.assertEqual(grown, {}, "IO-capable pathlib import outside adapters/ grew: %s" % grown)

    def test_a_baselined_file_with_one_more_offender_fails(self):
        before = {"x.py": 1}
        after = {"x.py": 2}
        self.assertEqual(grown_entries(before, after), {"x.py": (1, 2)})


class TestImportAst(unittest.TestCase):
    BASELINE = BASELINES / "forbidden_import_ast.txt"

    def test_flags_an_ast_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "thing.py").write_text("import ast\n")
            self.assertEqual(scan_import_ast(root), {"thing.py": 1})

    def test_does_not_flag_a_file_with_no_ast_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "thing.py").write_text("import json\n")
            self.assertEqual(scan_import_ast(root), {})

    def test_baseline_has_not_grown(self):
        before = parse_counts(self.BASELINE.read_text())
        after = scan_import_ast(LIGHTCYCLE, exclude_dirs=(ADAPTERS,))
        after_keyed = {"lightcycle/%s" % k: v for k, v in after.items()}
        grown = grown_entries(before, after_keyed)
        self.assertEqual(grown, {}, "import ast outside adapters/ grew: %s" % grown)

    def test_a_baselined_file_with_one_more_offender_fails(self):
        before = {"x.py": 1}
        after = {"x.py": 2}
        self.assertEqual(grown_entries(before, after), {"x.py": (1, 2)})


class TestOsExitCalls(unittest.TestCase):
    BASELINE = BASELINES / "os_exit.txt"

    def test_flags_an_os_exit_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "thing.py").write_text("import os\nos._exit(1)\n")
            self.assertEqual(scan_os_exit_calls(root), {"thing.py": 1})

    def test_does_not_flag_a_file_with_no_os_exit_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "thing.py").write_text("import sys\nsys.exit(1)\n")
            self.assertEqual(scan_os_exit_calls(root), {})

    def test_baseline_has_not_grown(self):
        before = parse_counts(self.BASELINE.read_text())
        after = scan_os_exit_calls(LIGHTCYCLE)
        after_keyed = {"lightcycle/%s" % k: v for k, v in after.items()}
        grown = grown_entries(before, after_keyed)
        self.assertEqual(grown, {}, "os._exit() calls grew: %s" % grown)

    def test_a_baselined_file_with_one_more_offender_fails(self):
        before = {"x.py": 1}
        after = {"x.py": 2}
        self.assertEqual(grown_entries(before, after), {"x.py": (1, 2)})


class TestUnmockedSubprocessInTestsUnit(unittest.TestCase):
    def test_flags_a_real_subprocess_run_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "thing.py").write_text("import subprocess\nsubprocess.run(['x'])\n")
            self.assertEqual(scan_unmocked_subprocess_calls(root), ["thing.py:2"])

    def test_does_not_flag_a_bare_exception_type_reference(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "thing.py").write_text(
                "import subprocess\n"
                "try:\n"
                "    pass\n"
                "except subprocess.CalledProcessError:\n"
                "    pass\n"
            )
            self.assertEqual(scan_unmocked_subprocess_calls(root), [])

    def test_no_unmocked_subprocess_calls_under_tests_unit(self):
        offenders = scan_unmocked_subprocess_calls(TESTS_UNIT)
        self.assertEqual(offenders, [], "unmocked subprocess call under tests/unit/: %s" % offenders)


if __name__ == "__main__":
    unittest.main()
