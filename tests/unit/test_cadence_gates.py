import contextlib
import io
import unittest

from lightcycle.application.pool.accrual_gates import AccrualGatesUseCase
from lightcycle.application.pool.cadence_gates import CadenceGatesUseCase
from lightcycle.config import ConfigError
from lightcycle.ports.git import GitReadError


class _Gate:
    def __init__(self, result=None, raises=None, log=None, name=""):
        self._result = result
        self._raises = raises
        self._log = log if log is not None else []
        self._name = name
        self.resets = 0

    def execute(self, *args):
        self._log.append(self._name)
        if self._raises:
            raise self._raises
        return self._result

    def reset(self):
        self.resets += 1


class TestCadenceGates(unittest.TestCase):
    def test_runs_the_three_gates_and_returns_each_result(self):
        cadence = CadenceGatesUseCase(_Gate("s"), _Gate("l"), _Gate("c"))
        result = cadence.execute(1.0)
        self.assertEqual((result.schedules, result.lifecycle, result.scripts), ("s", "l", "c"))

    def test_a_failing_gate_warns_and_yields_none_for_that_gate_only(self):
        cases = [
            (0, OSError("disk")), (0, GitReadError("git")), (0, ValueError("v")),
            (1, ConfigError("cfg")), (2, ConfigError("cfg")),
        ]
        for index, error in cases:
            gates = [_Gate("ok"), _Gate("ok"), _Gate("ok")]
            gates[index] = _Gate(raises=error)
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                result = CadenceGatesUseCase(*gates).execute(1.0)
            got = (result.schedules, result.lifecycle, result.scripts)
            self.assertIsNone(got[index])
            self.assertEqual([g for i, g in enumerate(got) if i != index], ["ok", "ok"])
            self.assertIn("warning:", err.getvalue())

    def test_reset_resets_all_three(self):
        gates = [_Gate(), _Gate(), _Gate()]
        CadenceGatesUseCase(*gates).reset()
        self.assertEqual([g.resets for g in gates], [1, 1, 1])


class TestAccrualGates(unittest.TestCase):
    def test_runs_usage_then_gh_call(self):
        log = []
        AccrualGatesUseCase(_Gate(log=log, name="usage"), _Gate(log=log, name="gh")).execute(1.0)
        self.assertEqual(log, ["usage", "gh"])


if __name__ == "__main__":
    unittest.main()
