import ast
import pathlib
import unittest

APPLICATION_ROOT = pathlib.Path(__file__).resolve().parents[1].parent / "lightcycle" / "application"

_WRITE_MODES = {"w", "a", "wb", "ab"}


def _is_os_makedirs(node):
    return (
        isinstance(node.func, ast.Attribute) and node.func.attr == "makedirs"
        and isinstance(node.func.value, ast.Name) and node.func.value.id == "os"
    )


def _is_os_path_isdir(node):
    return (
        isinstance(node.func, ast.Attribute) and node.func.attr == "isdir"
        and isinstance(node.func.value, ast.Attribute) and node.func.value.attr == "path"
        and isinstance(node.func.value.value, ast.Name) and node.func.value.value.id == "os"
    )


def _is_time_sleep(node):
    return (
        isinstance(node.func, ast.Attribute) and node.func.attr == "sleep"
        and isinstance(node.func.value, ast.Name) and node.func.value.id == "time"
    )


def _is_write_open(node):
    if not (isinstance(node.func, ast.Name) and node.func.id == "open"):
        return False
    args = list(node.args) + [kw.value for kw in node.keywords if kw.arg == "mode"]
    return any(isinstance(a, ast.Constant) and a.value in _WRITE_MODES for a in args)


class TestApplicationDoesNoRawFsIo(unittest.TestCase):
    def test_no_raw_makedirs_isdir_sleep_or_write_open_under_application(self):
        offenders = []
        for path in sorted(APPLICATION_ROOT.rglob("*.py")):
            tree = ast.parse(path.read_text(), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                if _is_os_makedirs(node) or _is_os_path_isdir(node) or _is_time_sleep(node) or _is_write_open(node):
                    offenders.append("%s:%d" % (path.relative_to(APPLICATION_ROOT.parent.parent), node.lineno))
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
