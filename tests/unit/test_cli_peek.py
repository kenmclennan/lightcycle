import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

import lightcycle.cli as cli_mod
from lightcycle.application.errors import UseCaseError
from lightcycle.cli import cmd_peek


class FakeContainer:
    def __init__(self, store=None, config=None, workflow_source=None):
        self.store = store
        self.config = config
        self.workflow_source = workflow_source


class TestCmdPeek(unittest.TestCase):
    def setUp(self):
        self._orig = cli_mod._container
        self.addCleanup(lambda: cli_mod.set_container(self._orig))

    def test_prints_the_resolved_pin_and_body(self):
        cli_mod.set_container(FakeContainer())
        fake_resp = mock.Mock(pin="acme/build@sha-new", body="the step body")
        with mock.patch.object(cli_mod, "_flow", lambda: object()), \
                mock.patch.object(cli_mod, "PeekStepUseCase") as UseCase:
            UseCase.return_value.execute.return_value = fake_resp
            out = io.StringIO()
            with redirect_stdout(out):
                rc = cmd_peek(["ITEM.1", "write-code"]) or 0
        self.assertEqual(rc, 0)
        self.assertIn("acme/build@sha-new", out.getvalue())
        self.assertIn("the step body", out.getvalue())

    def test_usecase_error_prints_to_stderr_and_returns_nonzero(self):
        cli_mod.set_container(FakeContainer())
        with mock.patch.object(cli_mod, "_flow", lambda: object()), \
                mock.patch.object(cli_mod, "PeekStepUseCase") as UseCase:
            UseCase.return_value.execute.side_effect = UseCaseError(
                "no workflow pin found for 'ITEM.1'")
            err = io.StringIO()
            with redirect_stderr(err):
                rc = cmd_peek(["ITEM.1", "write-code"])
        self.assertEqual(rc, 1)
        self.assertIn("no workflow pin found", err.getvalue())

    def test_unknown_node_prints_to_stderr_and_returns_nonzero(self):
        cli_mod.set_container(FakeContainer())
        with mock.patch.object(cli_mod, "_flow", lambda: object()), \
                mock.patch.object(cli_mod, "PeekStepUseCase") as UseCase:
            UseCase.return_value.execute.side_effect = KeyError("step not found: ITEM.1")
            err = io.StringIO()
            with redirect_stderr(err):
                rc = cmd_peek(["ITEM.1", "write-code"])
        self.assertEqual(rc, 1)
        self.assertIn("unknown node 'ITEM.1'", err.getvalue())


if __name__ == "__main__":
    unittest.main()
