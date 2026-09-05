import ast
import pathlib
import unittest

TESTS_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _base_names(cls):
    names = []
    for base in cls.bases:
        if isinstance(base, ast.Name):
            names.append(base.id)
        elif isinstance(base, ast.Attribute):
            names.append(base.attr)
    return names


def find_offending_classes(tree):
    offenders = []
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        method_names = {
            n.name for n in node.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        if "all_nodes" in method_names and "all_items" in method_names:
            if "StorePort" not in _base_names(node):
                offenders.append(node.name)
    return offenders


class TestFindOffendingClasses(unittest.TestCase):
    def test_flags_a_bare_pair(self):
        tree = ast.parse(
            "class FakeThing:\n"
            "    def all_nodes(self):\n"
            "        return []\n"
            "    def all_items(self):\n"
            "        return []\n"
        )
        self.assertEqual(find_offending_classes(tree), ["FakeThing"])

    def test_does_not_flag_a_storeport_subclass(self):
        tree = ast.parse(
            "class FakeThing(StorePort):\n"
            "    def all_nodes(self):\n"
            "        return []\n"
            "    def all_items(self):\n"
            "        return []\n"
        )
        self.assertEqual(find_offending_classes(tree), [])


class TestNoAdHocStoreDoubles(unittest.TestCase):
    def test_no_class_implements_the_store_pair_without_the_port(self):
        offenders = []
        for path in sorted(TESTS_ROOT.rglob("*.py")):
            tree = ast.parse(path.read_text(), filename=str(path))
            for name in find_offending_classes(tree):
                offenders.append("%s: %s" % (path.relative_to(TESTS_ROOT.parent), name))
        self.assertEqual(
            offenders, [], "ad-hoc StorePort-shaped double(s) found: %s" % offenders
        )


if __name__ == "__main__":
    unittest.main()
