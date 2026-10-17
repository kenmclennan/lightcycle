import ast
import pathlib
import tempfile
import unittest

from tests.support.baseline_counts import grown_entries, parse_counts

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
ADAPTERS = REPO_ROOT / "lightcycle" / "adapters"
BASELINE = pathlib.Path(__file__).resolve().parent / "baselines" / "subprocess_timeout.txt"
TIMEOUT_METHODS = {"run", "call", "check_call", "check_output"}
WAIT_METHODS = {"wait", "communicate"}
SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Module)


def subprocess_bindings(tree):
    modules = set()
    names = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "subprocess":
                    modules.add(alias.asname or "subprocess")
        elif isinstance(node, ast.ImportFrom) and node.module == "subprocess":
            for alias in node.names:
                names[alias.asname or alias.name] = alias.name
    return modules, names


def resolve_call(node, modules, names):
    func = node.func
    if isinstance(func, ast.Name):
        return names.get(func.id)
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        if func.value.id in modules:
            return func.attr
    return None


def parent_map(tree):
    return {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}


def bound_name(call, parents):
    parent = parents.get(call)
    if isinstance(parent, ast.Assign) and parent.value is call and len(parent.targets) == 1:
        target = parent.targets[0]
        return target.id if isinstance(target, ast.Name) else None
    if isinstance(parent, ast.withitem) and isinstance(parent.optional_vars, ast.Name):
        return parent.optional_vars.id
    return None


def enclosing_scope(node, parents):
    while not isinstance(node, SCOPES):
        node = parents[node]
    return node


def waited_with_timeout(scope, name):
    for node in ast.walk(scope):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in WAIT_METHODS:
            continue
        if not isinstance(node.func.value, ast.Name) or node.func.value.id != name:
            continue
        if any(kw.arg == "timeout" for kw in node.keywords):
            return True
    return False


def is_offender(node, method, parents):
    if method in TIMEOUT_METHODS:
        return not any(kw.arg == "timeout" for kw in node.keywords)
    if method == "Popen":
        name = bound_name(node, parents)
        if name is None:
            return True
        return not waited_with_timeout(enclosing_scope(node, parents), name)
    return False


def scan_missing_timeouts(root):
    counts = {}
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        modules, names = subprocess_bindings(tree)
        parents = parent_map(tree)
        offenders = 0
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            method = resolve_call(node, modules, names)
            if method and is_offender(node, method, parents):
                offenders += 1
        if offenders:
            counts[str(path.relative_to(root))] = offenders
    return counts


def scan_source(source):
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        (root / "thing.py").write_text(source)
        return scan_missing_timeouts(root)


class TestScanMissingTimeouts(unittest.TestCase):
    def test_flags_a_call_without_timeout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "thing.py").write_text("import subprocess\nsubprocess.run(['x'])\n")
            self.assertEqual(scan_missing_timeouts(root), {"thing.py": 1})

    def test_does_not_flag_a_call_with_timeout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "thing.py").write_text(
                "import subprocess\nsubprocess.run(['x'], timeout=5)\n"
            )
            self.assertEqual(scan_missing_timeouts(root), {})


    def test_flags_a_name_imported_run_without_timeout(self):
        self.assertEqual(
            scan_source("from subprocess import run\nrun(['x'])\n"), {"thing.py": 1})

    def test_flags_an_aliased_module_import_without_timeout(self):
        self.assertEqual(
            scan_source("import subprocess as sp\nsp.run(['x'])\n"), {"thing.py": 1})

    def test_flags_an_aliased_name_import_without_timeout(self):
        self.assertEqual(
            scan_source("from subprocess import Popen as P\ndef f():\n    P(['x'])\n"),
            {"thing.py": 1})

    def test_does_not_flag_a_popen_waited_on_with_a_timeout(self):
        source = (
            "import subprocess\n"
            "def f():\n"
            "    p = subprocess.Popen(['x'])\n"
            "    p.wait(timeout=5)\n"
        )
        self.assertEqual(scan_source(source), {})

    def test_does_not_flag_a_popen_communicated_with_a_timeout(self):
        source = (
            "from subprocess import Popen\n"
            "def f():\n"
            "    p = Popen(['x'])\n"
            "    p.communicate(timeout=5)\n"
        )
        self.assertEqual(scan_source(source), {})

    def test_does_not_flag_a_context_managed_popen_waited_on_with_a_timeout(self):
        source = (
            "import subprocess\n"
            "def f():\n"
            "    with subprocess.Popen(['x']) as p:\n"
            "        p.wait(timeout=5)\n"
        )
        self.assertEqual(scan_source(source), {})

    def test_flags_a_popen_with_a_bare_wait(self):
        source = (
            "import subprocess\n"
            "def f():\n"
            "    p = subprocess.Popen(['x'])\n"
            "    p.wait()\n"
        )
        self.assertEqual(scan_source(source), {"thing.py": 1})

    def test_flags_a_popen_returned_from_the_function(self):
        source = "import subprocess\ndef f():\n    return subprocess.Popen(['x'])\n"
        self.assertEqual(scan_source(source), {"thing.py": 1})

    def test_flags_a_popen_waited_on_with_a_timeout_in_another_function(self):
        source = (
            "import subprocess\n"
            "def f():\n"
            "    p = subprocess.Popen(['x'])\n"
            "def g(p):\n"
            "    p.wait(timeout=5)\n"
        )
        self.assertEqual(scan_source(source), {"thing.py": 1})


class TestSubprocessTimeoutBaseline(unittest.TestCase):
    def test_adapters_do_not_exceed_the_committed_baseline(self):
        before = parse_counts(BASELINE.read_text())
        after = scan_missing_timeouts(ADAPTERS)
        after_keyed = {"lightcycle/adapters/%s" % k: v for k, v in after.items()}
        grown = grown_entries(before, after_keyed)
        self.assertEqual(grown, {}, "subprocess calls missing timeout= grew: %s" % grown)

    def test_a_baselined_file_with_one_more_offender_fails(self):
        before = {"x.py": 1}
        after = {"x.py": 2}
        self.assertEqual(grown_entries(before, after), {"x.py": (1, 2)})


if __name__ == "__main__":
    unittest.main()
