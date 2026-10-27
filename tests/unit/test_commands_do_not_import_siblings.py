import ast
import unittest
from pathlib import Path

COMMANDS_DIR = Path(__file__).resolve().parents[2] / "lightcycle" / "commands"
SHARED = {"context", "shared"}


def _sibling_imports(path):
    found = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.ImportFrom) and node.module:
            parts = node.module.split(".")
            if parts[:2] == ["lightcycle", "commands"]:
                if len(parts) > 2:
                    found.add(parts[2])
                else:
                    found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                parts = alias.name.split(".")
                if parts[:2] == ["lightcycle", "commands"] and len(parts) > 2:
                    found.add(parts[2])
    return found


class TestCommandModulesDoNotImportSiblings(unittest.TestCase):
    def test_no_command_module_imports_a_peer_except_the_shared_ones(self):
        offenders = {}
        for path in sorted(COMMANDS_DIR.glob("*.py")):
            if path.stem in SHARED or path.stem == "__init__":
                continue
            bad = _sibling_imports(path) - SHARED
            if bad:
                offenders[path.name] = sorted(bad)
        self.assertEqual(offenders, {})
