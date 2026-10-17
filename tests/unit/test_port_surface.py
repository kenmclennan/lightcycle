import ast
import pathlib
import re
import tempfile
import unittest

from tests.support.baseline_counts import grown_entries, parse_counts

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
LIGHTCYCLE = REPO_ROOT / "lightcycle"
PORTS = LIGHTCYCLE / "ports"
APPLICATION = LIGHTCYCLE / "application"
BASELINES = pathlib.Path(__file__).resolve().parent / "baselines"
UNDECLARED_BASELINE = BASELINES / "undeclared_port_calls.txt"
DEAD_BASELINE = BASELINES / "dead_port_methods.txt"


def _snake(name):
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def _is_abstract(func):
    for decorator in func.decorator_list:
        name = decorator.attr if isinstance(decorator, ast.Attribute) else getattr(decorator, "id", "")
        if name == "abstractmethod":
            return True
    return False


def _is_port_class(node):
    return isinstance(node, ast.ClassDef) and any(
        isinstance(b, ast.Name) and b.id == "ABC" for b in node.bases
    )


def port_surfaces(ports_root):
    surfaces = {}
    for path in sorted(ports_root.glob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in tree.body:
            if not _is_port_class(node):
                continue
            methods = {
                n.name: _is_abstract(n) for n in node.body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
            surfaces[node.name] = (path.stem, methods)
    return surfaces


def _receiver_key(name):
    name = name.lstrip("_")
    if name.endswith("_port"):
        name = name[: -len("_port")]
    return name


def receiver_ports(surfaces):
    mapping = {}
    for port_name, (stem, _) in surfaces.items():
        mapping[stem] = port_name
        mapping[_receiver_key(_snake(port_name))] = port_name
    return mapping


def undeclared_port_calls(root, surfaces, relative_to):
    mapping = receiver_ports(surfaces)
    counts = {}
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        found = 0
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            receiver = node.func.value
            if not (
                isinstance(receiver, ast.Attribute)
                and isinstance(receiver.value, ast.Name)
                and receiver.value.id == "self"
                and receiver.attr.startswith("_")
            ):
                continue
            port = mapping.get(_receiver_key(receiver.attr))
            if port is not None and node.func.attr not in surfaces[port][1]:
                found += 1
        if found:
            counts[str(path.relative_to(relative_to))] = found
    return counts


def dead_port_methods(lightcycle_root, ports_root, surfaces, relative_to):
    called = set()
    for path in sorted(lightcycle_root.rglob("*.py")):
        if ports_root in path.parents:
            continue
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                called.add(node.func.attr)
    counts = {}
    for port_name, (stem, methods) in surfaces.items():
        dead = [m for m, abstract in methods.items() if abstract and m not in called]
        if dead:
            key = str((ports_root / ("%s.py" % stem)).relative_to(relative_to))
            counts[key] = counts.get(key, 0) + len(dead)
    return counts


def _write(root, name, text):
    (root / name).write_text(text)


PORT_SOURCE = (
    "from abc import ABC, abstractmethod\n"
    "class WidgetPort(ABC):\n"
    "    @abstractmethod\n"
    "    def used(self):\n"
    "        pass\n"
    "    @abstractmethod\n"
    "    def unused(self):\n"
    "        pass\n"
)


class TestPortsAreExported(unittest.TestCase):
    def test_every_port_abc_is_exported_from_the_ports_package(self):
        from lightcycle.ports import __all__ as exported

        missing = set(port_surfaces(PORTS)) - set(exported)
        self.assertEqual(missing, set(), "ports not exported from ports/__init__.py: %s" % sorted(missing))


class TestUndeclaredPortCalls(unittest.TestCase):
    def test_flags_a_call_the_mapped_port_does_not_declare(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            ports = root / "ports"
            app = root / "app"
            ports.mkdir()
            app.mkdir()
            _write(ports, "widget.py", PORT_SOURCE)
            _write(app, "thing.py", "class T:\n    def run(self):\n        self._widget.missing()\n        self._widget.used()\n")
            counts = undeclared_port_calls(app, port_surfaces(ports), root)
            self.assertEqual(counts, {"app/thing.py": 1})

    def test_ignores_a_receiver_that_maps_to_no_port(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            ports = root / "ports"
            app = root / "app"
            ports.mkdir()
            app.mkdir()
            _write(ports, "widget.py", PORT_SOURCE)
            _write(app, "thing.py", "class T:\n    def run(self):\n        self._other.missing()\n")
            self.assertEqual(undeclared_port_calls(app, port_surfaces(ports), root), {})

    def test_maps_a_port_suffixed_receiver_to_its_port(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            ports = root / "ports"
            app = root / "app"
            ports.mkdir()
            app.mkdir()
            _write(ports, "widget.py", PORT_SOURCE)
            _write(app, "thing.py", "class T:\n    def run(self):\n        self._widget_port.missing()\n")
            self.assertEqual(undeclared_port_calls(app, port_surfaces(ports), root), {"app/thing.py": 1})

    def test_baseline_has_not_grown(self):
        before = parse_counts(UNDECLARED_BASELINE.read_text())
        after = undeclared_port_calls(APPLICATION, port_surfaces(PORTS), REPO_ROOT)
        self.assertEqual(
            grown_entries(before, after), {}, "undeclared port method calls grew: %s" % grown_entries(before, after)
        )


class TestDeadPortMethods(unittest.TestCase):
    def test_flags_an_abstract_method_nothing_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            ports = root / "ports"
            app = root / "app"
            ports.mkdir()
            app.mkdir()
            _write(ports, "widget.py", PORT_SOURCE)
            _write(app, "thing.py", "def run(w):\n    w.used()\n")
            counts = dead_port_methods(root, ports, port_surfaces(ports), root)
            self.assertEqual(counts, {"ports/widget.py": 1})

    def test_a_call_inside_the_ports_package_does_not_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            ports = root / "ports"
            ports.mkdir()
            _write(ports, "widget.py", PORT_SOURCE + "def helper(w):\n    w.used()\n    w.unused()\n")
            counts = dead_port_methods(root, ports, port_surfaces(ports), root)
            self.assertEqual(counts, {"ports/widget.py": 2})

    def test_baseline_has_not_grown(self):
        before = parse_counts(DEAD_BASELINE.read_text())
        after = dead_port_methods(LIGHTCYCLE, PORTS, port_surfaces(PORTS), REPO_ROOT)
        self.assertEqual(
            grown_entries(before, after), {}, "dead port methods grew: %s" % grown_entries(before, after)
        )


if __name__ == "__main__":
    unittest.main()
