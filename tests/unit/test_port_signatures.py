import importlib
import inspect
import pathlib
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
PORTS_DIR = REPO_ROOT / "lightcycle" / "ports"
IMPL_DIRS = [REPO_ROOT / "lightcycle" / "adapters", REPO_ROOT / "tests" / "support"]


def _module_name(path):
    return ".".join(path.relative_to(REPO_ROOT).with_suffix("").parts)


def _own_classes(module):
    return [obj for _, obj in vars(module).items()
            if inspect.isclass(obj) and obj.__module__ == module.__name__]


def _discover_ports():
    ports = {}
    for path in sorted(PORTS_DIR.glob("*.py")):
        if path.name == "__init__.py":
            continue
        for cls in _own_classes(importlib.import_module(_module_name(path))):
            if getattr(cls, "__abstractmethods__", None):
                ports[cls] = cls.__abstractmethods__
    return ports


def _discover_impls():
    impls = []
    for d in IMPL_DIRS:
        for path in sorted(d.rglob("*.py")):
            if path.name == "__init__.py":
                continue
            for cls in _own_classes(importlib.import_module(_module_name(path))):
                if not inspect.isabstract(cls):
                    impls.append(cls)
    return impls


def _shape(func):
    return [(n, p.kind.name) for n, p in inspect.signature(func).parameters.items() if n != "self"]


def compare_method(port_cls, impl_cls, name):
    port_shape = _shape(getattr(port_cls, name))
    impl_shape = _shape(impl_cls.__dict__[name])
    if port_shape == impl_shape:
        return None
    return "%s.%s.%s: port declares %s, implementation declares %s" % (
        impl_cls.__module__, impl_cls.__name__, name, port_shape, impl_shape)


def find_signature_mismatches():
    mismatches = []
    for impl_cls in _discover_impls():
        for port_cls, method_names in _discover_ports().items():
            if not issubclass(impl_cls, port_cls):
                continue
            for name in method_names:
                if name not in impl_cls.__dict__:
                    continue
                mismatch = compare_method(port_cls, impl_cls, name)
                if mismatch:
                    mismatches.append(mismatch)
    return mismatches


class TestAdapterSignaturesMatchTheirPort(unittest.TestCase):
    def test_no_implementation_diverges_from_its_port(self):
        mismatches = find_signature_mismatches()
        self.assertEqual(mismatches, [], "\n".join(mismatches))


class TestCompareMethodDetectsMismatches(unittest.TestCase):
    def test_flags_a_widened_parameter_list(self):
        class Port:
            def m(self, a):
                pass

        class Impl(Port):
            def m(self, a, b=None):
                pass

        self.assertIsNotNone(compare_method(Port, Impl, "m"))

    def test_reports_none_for_identical_shapes(self):
        class Port:
            def m(self, a, *, b=None):
                pass

        class Impl(Port):
            def m(self, a, *, b=None):
                pass

        self.assertIsNone(compare_method(Port, Impl, "m"))
