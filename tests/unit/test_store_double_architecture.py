import ast
import pathlib
import unittest

from lightcycle.ports import __all__ as PORT_NAMES

TESTS_ROOT = pathlib.Path(__file__).resolve().parents[1]
LIGHTCYCLE_ROOT = TESTS_ROOT.parent / "lightcycle"
PORTS_ROOT = LIGHTCYCLE_ROOT / "ports"


def _base_names(cls):
    names = []
    for base in cls.bases:
        if isinstance(base, ast.Name):
            names.append(base.id)
        elif isinstance(base, ast.Attribute):
            names.append(base.attr)
    return names


def _method_names(cls):
    return {
        n.name for n in cls.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _port_abstract_methods(port_name):
    for path in sorted(PORTS_ROOT.glob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name == port_name:
                return _method_names(node)
    raise AssertionError("port %s not found under %s" % (port_name, PORTS_ROOT))


def find_offending_classes(tree, port_name, port_methods):
    offenders = []
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        if not port_methods <= _method_names(node):
            continue
        if port_name not in _base_names(node):
            offenders.append(node.name)
    return offenders


class TestFindOffendingClasses(unittest.TestCase):
    def test_flags_a_bare_shape_match(self):
        tree = ast.parse(
            "class FakeThing:\n"
            "    def all_nodes(self):\n"
            "        return []\n"
            "    def all_items(self):\n"
            "        return []\n"
        )
        offenders = find_offending_classes(tree, "StorePort", {"all_nodes", "all_items"})
        self.assertEqual(offenders, ["FakeThing"])

    def test_does_not_flag_a_declared_subclass(self):
        tree = ast.parse(
            "class FakeThing(StorePort):\n"
            "    def all_nodes(self):\n"
            "        return []\n"
            "    def all_items(self):\n"
            "        return []\n"
        )
        offenders = find_offending_classes(tree, "StorePort", {"all_nodes", "all_items"})
        self.assertEqual(offenders, [])

    def test_does_not_flag_a_partial_implementation(self):
        tree = ast.parse(
            "class FakeThing:\n"
            "    def all_nodes(self):\n"
            "        return []\n"
        )
        offenders = find_offending_classes(tree, "StorePort", {"all_nodes", "all_items"})
        self.assertEqual(offenders, [])


class TestNoAdHocPortDoubles(unittest.TestCase):
    def test_no_class_implements_a_ports_full_surface_without_declaring_it(self):
        paths = sorted(TESTS_ROOT.rglob("*.py"))
        trees = [(path, ast.parse(path.read_text(), filename=str(path))) for path in paths]
        offenders = []
        for port_name in PORT_NAMES:
            port_methods = _port_abstract_methods(port_name)
            if not port_methods:
                continue
            for path, tree in trees:
                for name in find_offending_classes(tree, port_name, port_methods):
                    offenders.append(
                        "%s: %s (%s)" % (path.relative_to(TESTS_ROOT.parent), name, port_name)
                    )
        self.assertEqual(
            offenders, [], "ad-hoc port-shaped double(s) found: %s" % offenders
        )


def _declared_store_port_methods():
    return _port_abstract_methods("StorePort")


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
