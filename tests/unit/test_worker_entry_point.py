import ast
import importlib.util
import pathlib
import unittest

LIGHTCYCLE = pathlib.Path(__file__).resolve().parents[2] / "lightcycle"


def _spawn_module():
    tree = ast.parse((LIGHTCYCLE / "adapters" / "spawner.py").read_text())
    for node in ast.walk(tree):
        if not isinstance(node, ast.List):
            continue
        parts = [e.value for e in node.elts if isinstance(e, ast.Constant)]
        if "-m" in parts:
            return parts[parts.index("-m") + 1]
    return None


class TestWorkerEntryPoint(unittest.TestCase):
    def test_the_spawner_launches_a_module_that_exists(self):
        name = _spawn_module()
        self.assertIsNotNone(name, "spawner builds no `-m` command")
        self.assertIsNotNone(
            importlib.util.find_spec(name), "spawner launches %r, which is not importable" % name
        )

    def test_the_launched_module_defines_main(self):
        name = _spawn_module()
        path = LIGHTCYCLE.parent / (name.replace(".", "/") + ".py")
        tree = ast.parse(path.read_text())
        names = [n.name for n in tree.body if isinstance(n, ast.FunctionDef)]
        self.assertIn("main", names)

    def test_the_session_adapter_is_no_longer_an_entry_point(self):
        tree = ast.parse((LIGHTCYCLE / "adapters" / "worker_session.py").read_text())
        names = [n.name for n in tree.body if isinstance(n, ast.FunctionDef)]
        self.assertNotIn("main", names)
