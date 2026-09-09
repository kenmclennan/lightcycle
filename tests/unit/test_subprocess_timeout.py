import ast
import pathlib
import tempfile
import unittest

from tests.support.baseline_counts import grown_entries, parse_counts

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
ADAPTERS = REPO_ROOT / "lightcycle" / "adapters"
BASELINE = pathlib.Path(__file__).resolve().parent / "baselines" / "subprocess_timeout.txt"
TIMEOUT_METHODS = {"run", "Popen", "call", "check_call", "check_output"}


def scan_missing_timeouts(root):
    counts = {}
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        offenders = 0
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Attribute) or func.attr not in TIMEOUT_METHODS:
                continue
            if not isinstance(func.value, ast.Name) or func.value.id != "subprocess":
                continue
            if not any(kw.arg == "timeout" for kw in node.keywords):
                offenders += 1
        if offenders:
            counts[str(path.relative_to(root))] = offenders
    return counts


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
