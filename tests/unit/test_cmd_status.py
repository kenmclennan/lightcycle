import io
import unittest
from contextlib import redirect_stdout
from unittest import mock

import lightcycle.cli as cli_mod
from lightcycle.cli import cmd_status
from lightcycle.domain.work import Node


class FakeContainer:
    def __init__(self, store=None):
        self.store = store


class _FixedFlowService:
    def __init__(self, phrases):
        self._phrases = phrases

    def display_for(self, node):
        return self._phrases.get(node.step)


class TestCmdStatusDisplayPhrase(unittest.TestCase):
    def setUp(self):
        self._orig = cli_mod._container
        self.addCleanup(lambda: cli_mod.set_container(self._orig))
        cli_mod.set_container(FakeContainer())

    def _run(self, lanes, flow_service):
        fake_resp = mock.Mock(lanes=lanes)
        with mock.patch.object(cli_mod, "StatusUseCase") as UseCase, \
                mock.patch.object(cli_mod, "_flow", lambda: flow_service):
            UseCase.return_value.execute.return_value = fake_resp
            out = io.StringIO()
            with redirect_stdout(out):
                rc = cmd_status([]) or 0
        return rc, out.getvalue()

    def test_shows_the_phrase_and_stage_when_a_phrase_is_declared(self):
        node = Node(id="t1", title="one", step="code-await-merge")
        lanes = {"inbox": [node], "active": [], "queue": []}
        rc, out = self._run(lanes, _FixedFlowService({"code-await-merge": "Review the PR"}))
        self.assertEqual(rc, 0)
        self.assertIn("Review the PR · code-await-merge", out)

    def test_shows_the_bare_stage_when_no_phrase_is_declared(self):
        node = Node(id="t1", title="one", step="build")
        lanes = {"inbox": [node], "active": [], "queue": []}
        rc, out = self._run(lanes, _FixedFlowService({}))
        line = next(l for l in out.splitlines() if "t1" in l)
        self.assertTrue(line.endswith("  build"))


if __name__ == "__main__":
    unittest.main()
