import ast
import pathlib
import unittest

TESTS_ROOT = pathlib.Path(__file__).resolve().parents[1]
LIGHTCYCLE_ROOT = TESTS_ROOT.parent / "lightcycle"


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


def _declared_store_port_methods():
    tree = ast.parse((LIGHTCYCLE_ROOT / "ports" / "store.py").read_text())
    cls = next(
        n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "StorePort"
    )
    return {
        n.name for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _is_store_receiver(receiver):
    if isinstance(receiver, ast.Name) and receiver.id == "store":
        return True
    if isinstance(receiver, ast.Attribute) and receiver.attr in ("store", "_store"):
        return True
    return False


def _store_call_names(tree):
    names = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute):
            continue
        if _is_store_receiver(func.value):
            names.append(func.attr)
    return names


class TestStorePortDeclaresEverythingCalled(unittest.TestCase):
    def test_no_undeclared_method_is_called_on_a_store_receiver(self):
        declared = _declared_store_port_methods()
        undeclared = set()
        for path in sorted(LIGHTCYCLE_ROOT.rglob("*.py")):
            rel = path.relative_to(LIGHTCYCLE_ROOT)
            if rel.parts[0] in ("adapters", "ports"):
                continue
            tree = ast.parse(path.read_text(), filename=str(path))
            for name in _store_call_names(tree):
                if name not in declared:
                    undeclared.add("%s: %s" % (rel, name))
        self.assertEqual(
            undeclared, set(), "undeclared store method(s) called: %s" % sorted(undeclared)
        )


if __name__ == "__main__":
    unittest.main()
