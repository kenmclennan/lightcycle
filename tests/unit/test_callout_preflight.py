import json
import unittest

from lightcycle.application.inspect.callout_preflight import CalloutPreflightUseCase
from lightcycle.domain.work.callout_preflight import VERB_FIX
from lightcycle.ports.script_runner import ScriptResult
from tests.support.callout_rig import StubConfig, callout, preflight_failed, preflight_ok
from tests.support.fake_script_runner import FakeScriptRunner


def _check(result, timeout=30, context="doctor"):
    runner = FakeScriptRunner()
    c = callout("a", timeout=timeout)
    runner.program_run(c.command, result)
    errors = CalloutPreflightUseCase(StubConfig([c]), runner).check(c, context)
    return errors, runner


class TestCheck(unittest.TestCase):
    def test_ok_returns_no_errors(self):
        self.assertEqual(_check(preflight_ok())[0], [])

    def test_failed_returns_the_errors(self):
        errors, _ = _check(preflight_failed(("m1", "f1"), ("m2", "f2")))

        self.assertEqual([(e.message, e.fix) for e in errors], [("m1", "f1"), ("m2", "f2")])

    def test_exit_timeout_and_invalid_output_each_give_one_engine_error(self):
        for result in (
            ScriptResult(exit_code=1), ScriptResult(exit_code=None, timed_out=True),
            ScriptResult(exit_code=None), ScriptResult(exit_code=0, stdout="nope"),
        ):
            errors, _ = _check(result)

            self.assertEqual(len(errors), 1)
            self.assertEqual(errors[0].fix, VERB_FIX)
            self.assertTrue(errors[0].message.startswith("preflight: "))

    def test_a_runner_that_raises_gives_an_engine_error_not_an_exception(self):
        class Raising(FakeScriptRunner):
            def run(self, *a, **k):
                raise OSError("gone")

        c = callout("a")

        errors = CalloutPreflightUseCase(StubConfig([c]), Raising()).check(c, "doctor")

        self.assertIn("gone", errors[0].message)

    def test_the_stdin_has_the_context_and_null_item_step_and_repos(self):
        _, runner = _check(preflight_ok(), context="register")

        request = json.loads(runner.calls[0]["stdin"])
        self.assertEqual(request["context"], "register")
        self.assertEqual(request["verb"], "preflight")
        self.assertEqual(request["protocol"], 2)
        for key in ("item", "step", "repos"):
            self.assertIsNone(request[key])

    def test_the_timeout_is_capped_at_thirty_seconds(self):
        self.assertEqual(_check(preflight_ok(), timeout=10)[1].calls[0]["timeout"], 10)
        self.assertEqual(_check(preflight_ok(), timeout=60)[1].calls[0]["timeout"], 30)
