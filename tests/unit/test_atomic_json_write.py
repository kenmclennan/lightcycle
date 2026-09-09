import ast
import pathlib
import tempfile
import unittest

from tests.support.baseline_counts import grown_entries, parse_counts

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
ADAPTERS = REPO_ROOT / "lightcycle" / "adapters"
BASELINE = pathlib.Path(__file__).resolve().parent / "baselines" / "atomic_json_write.txt"


def _writes_json(node):
    for n in ast.walk(node):
        if not isinstance(n, ast.Call):
            continue
        func = n.func
        if isinstance(func, ast.Attribute) and func.attr == "dump":
            if isinstance(func.value, ast.Name) and func.value.id == "json":
                return True
        if isinstance(func, ast.Attribute) and func.attr == "write":
            for arg in n.args:
                if isinstance(arg, ast.Call):
                    inner = arg.func
                    if isinstance(inner, ast.Attribute) and inner.attr == "dumps":
                        if isinstance(inner.value, ast.Name) and inner.value.id == "json":
                            return True
    return False


def _calls_os_replace(node):
    for n in ast.walk(node):
        if not isinstance(n, ast.Call):
            continue
        func = n.func
        if isinstance(func, ast.Attribute) and func.attr == "replace":
            if isinstance(func.value, ast.Name) and func.value.id == "os":
                return True
    return False


def scan_missing_atomic_writes(root):
    counts = {}
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        offenders = 0
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if _writes_json(node) and not _calls_os_replace(node):
                offenders += 1
        if offenders:
            counts[str(path.relative_to(root))] = offenders
    return counts


class TestScanMissingAtomicWrites(unittest.TestCase):
    def test_flags_a_json_dump_without_os_replace(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "thing.py").write_text(
                "import json\n"
                "def save(path, data):\n"
                "    with open(path, 'w') as f:\n"
                "        json.dump(data, f)\n"
            )
            self.assertEqual(scan_missing_atomic_writes(root), {"thing.py": 1})

    def test_does_not_flag_a_json_dump_with_os_replace(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "thing.py").write_text(
                "import json\n"
                "import os\n"
                "def save(path, data):\n"
                "    with open(path + '.tmp', 'w') as f:\n"
                "        json.dump(data, f)\n"
                "    os.replace(path + '.tmp', path)\n"
            )
            self.assertEqual(scan_missing_atomic_writes(root), {})


class TestAtomicJsonWriteBaseline(unittest.TestCase):
    def test_adapters_do_not_exceed_the_committed_baseline(self):
        before = parse_counts(BASELINE.read_text())
        after = scan_missing_atomic_writes(ADAPTERS)
        after_keyed = {"lightcycle/adapters/%s" % k: v for k, v in after.items()}
        grown = grown_entries(before, after_keyed)
        self.assertEqual(grown, {}, "JSON writes missing os.replace grew: %s" % grown)

    def test_a_baselined_file_with_one_more_offender_fails(self):
        before = {"x.py": 1}
        after = {"x.py": 2}
        self.assertEqual(grown_entries(before, after), {"x.py": (1, 2)})


if __name__ == "__main__":
    unittest.main()
