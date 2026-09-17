import ast
import pathlib
import tempfile
import unittest

from tests.support.baseline_counts import grown_entries, parse_counts

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
APPLICATION = REPO_ROOT / "lightcycle" / "application"
BASELINE = pathlib.Path(__file__).resolve().parent / "baselines" / "required_collaborators.txt"


def _optional_param_count(init):
    args = init.args
    n_positional_defaults = len(args.defaults)
    defaulted_positional = args.args[len(args.args) - n_positional_defaults:]
    defaulted_kwonly = [
        arg for arg, default in zip(args.kwonlyargs, args.kw_defaults) if default is not None
    ]
    return len(defaulted_positional) + len(defaulted_kwonly)


def scan_optional_use_case_constructor_params(root):
    counts = {}
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        offenders = 0
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef) or not node.name.endswith("UseCase"):
                continue
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == "__init__":
                    offenders += _optional_param_count(item)
        if offenders:
            counts[str(path.relative_to(root))] = offenders
    return counts


class TestScanOptionalUseCaseConstructorParams(unittest.TestCase):
    def test_flags_an_optional_constructor_param(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "thing.py").write_text(
                "class FooUseCase:\n"
                "    def __init__(self, a, b=None):\n"
                "        pass\n"
            )
            self.assertEqual(scan_optional_use_case_constructor_params(root), {"thing.py": 1})

    def test_does_not_flag_a_required_constructor_param(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "thing.py").write_text(
                "class FooUseCase:\n"
                "    def __init__(self, a, b):\n"
                "        pass\n"
            )
            self.assertEqual(scan_optional_use_case_constructor_params(root), {})

    def test_does_not_flag_a_class_not_named_use_case(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "thing.py").write_text(
                "class FooHelper:\n"
                "    def __init__(self, a, b=None):\n"
                "        pass\n"
            )
            self.assertEqual(scan_optional_use_case_constructor_params(root), {})

    def test_baseline_has_not_grown(self):
        before = parse_counts(BASELINE.read_text())
        after = scan_optional_use_case_constructor_params(APPLICATION)
        after_keyed = {"lightcycle/application/%s" % k: v for k, v in after.items()}
        grown = grown_entries(before, after_keyed)
        self.assertEqual(
            grown, {}, "use cases with optional constructor params grew: %s" % grown
        )

    def test_a_class_already_covered_by_the_seeded_baseline_at_its_current_count_is_not_flagged(self):
        before = {"x.py": 1}
        after = {"x.py": 1}
        self.assertEqual(grown_entries(before, after), {})

    def test_a_baselined_file_with_one_more_offender_fails(self):
        before = {"x.py": 1}
        after = {"x.py": 2}
        self.assertEqual(grown_entries(before, after), {"x.py": (1, 2)})


if __name__ == "__main__":
    unittest.main()
