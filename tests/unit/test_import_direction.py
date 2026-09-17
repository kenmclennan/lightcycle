import ast
import pathlib
import tempfile
import unittest

from tests.support.baseline_counts import grown_entries, parse_counts

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
LIGHTCYCLE = REPO_ROOT / "lightcycle"
BASELINES = pathlib.Path(__file__).resolve().parent / "baselines"

PACKAGE_OWN_NAMES = {"__version__"}


def _paths(root):
    return sorted(root.rglob("*.py"))


def scan_parent_package_imports(root):
    counts = {}
    for path in _paths(root):
        tree = ast.parse(path.read_text(), filename=str(path))
        offenders = 0
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "lightcycle" and not node.level:
                for alias in node.names:
                    if alias.name not in PACKAGE_OWN_NAMES:
                        offenders += 1
        if offenders:
            counts[str(path.relative_to(root))] = offenders
    return counts


def scan_function_local_first_party_imports(root):
    counts = {}
    for path in _paths(root):
        tree = ast.parse(path.read_text(), filename=str(path))
        offenders = 0
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for inner in ast.walk(node):
                if inner is node:
                    continue
                if isinstance(inner, ast.Import):
                    offenders += sum(
                        1 for alias in inner.names
                        if alias.name == "lightcycle" or alias.name.startswith("lightcycle.")
                    )
                elif isinstance(inner, ast.ImportFrom):
                    if inner.module and (
                        inner.module == "lightcycle" or inner.module.startswith("lightcycle.")
                    ):
                        offenders += 1
        if offenders:
            counts[str(path.relative_to(root))] = offenders
    return counts


class TestParentPackageImports(unittest.TestCase):
    BASELINE = BASELINES / "parent_package_imports.txt"

    def test_flags_a_sibling_submodule_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "thing.py").write_text("from lightcycle import frontmatter\n")
            self.assertEqual(scan_parent_package_imports(root), {"thing.py": 1})

    def test_does_not_flag_the_packages_own_version_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "thing.py").write_text("from lightcycle import __version__\n")
            self.assertEqual(scan_parent_package_imports(root), {})

    def test_baseline_has_not_grown(self):
        before = parse_counts(self.BASELINE.read_text())
        after = scan_parent_package_imports(LIGHTCYCLE)
        after_keyed = {"lightcycle/%s" % k: v for k, v in after.items()}
        grown = grown_entries(before, after_keyed)
        self.assertEqual(grown, {}, "parent-package imports grew: %s" % grown)

    def test_a_baselined_file_with_one_more_offender_fails(self):
        before = {"x.py": 1}
        after = {"x.py": 2}
        self.assertEqual(grown_entries(before, after), {"x.py": (1, 2)})


class TestFunctionLocalFirstPartyImports(unittest.TestCase):
    BASELINE = BASELINES / "function_local_first_party_imports.txt"

    def test_flags_a_function_local_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "thing.py").write_text(
                "def f():\n"
                "    from lightcycle.domain.work import worker_permitted\n"
                "    return worker_permitted\n"
            )
            self.assertEqual(scan_function_local_first_party_imports(root), {"thing.py": 1})

    def test_does_not_flag_a_module_level_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "thing.py").write_text(
                "from lightcycle.domain.work import worker_permitted\n"
                "def f():\n"
                "    return worker_permitted\n"
            )
            self.assertEqual(scan_function_local_first_party_imports(root), {})

    def test_baseline_has_not_grown(self):
        before = parse_counts(self.BASELINE.read_text())
        after = scan_function_local_first_party_imports(LIGHTCYCLE)
        after_keyed = {"lightcycle/%s" % k: v for k, v in after.items()}
        grown = grown_entries(before, after_keyed)
        self.assertEqual(grown, {}, "function-local first-party imports grew: %s" % grown)

    def test_a_baselined_file_with_one_more_offender_fails(self):
        before = {"x.py": 1}
        after = {"x.py": 2}
        self.assertEqual(grown_entries(before, after), {"x.py": (1, 2)})


if __name__ == "__main__":
    unittest.main()
