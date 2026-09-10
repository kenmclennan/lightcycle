import ast
import pathlib
import unittest

LIGHTCYCLE = pathlib.Path(__file__).resolve().parents[2] / "lightcycle"
COMPOSITION_ROOTS = ("cli.py", "container.py", "worker_main.py")
WIRED_BY_THE_CONTAINER = (
    "TickUseCase",
    "SweepUseCase",
    "MonitorPrsUseCase",
    "BreakerGateUseCase",
    "RetroCadenceUseCase",
    "HookCompletionsUseCase",
    "BackupUseCase",
    "LiveUsageAccrualUseCase",
)


def _constructed_names(path):
    tree = ast.parse(path.read_text())
    return {
        n.func.id for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }


class TestPoolGraphIsWiredInOnePlace(unittest.TestCase):
    def test_cli_does_not_rebuild_what_the_container_wires(self):
        built = _constructed_names(LIGHTCYCLE / "cli.py")
        offenders = sorted(built.intersection(WIRED_BY_THE_CONTAINER))
        self.assertEqual(
            offenders, [],
            "cli.py wires collaborators the container owns, so the two can disagree: %s" % offenders,
        )

    def test_only_the_named_modules_construct_a_store(self):
        offenders = []
        for path in sorted(LIGHTCYCLE.rglob("*.py")):
            if path.name in COMPOSITION_ROOTS:
                continue
            if "SqliteStore" in _constructed_names(path):
                offenders.append(str(path.relative_to(LIGHTCYCLE)))
        self.assertEqual(offenders, [], "a store is built outside the composition roots: %s" % offenders)
