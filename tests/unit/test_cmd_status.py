import io
import unittest
from contextlib import redirect_stdout
from unittest import mock

import lightcycle.cli as cli_mod
from lightcycle.cli import cmd_status
from tests.support.fake_drain import FakeDrain
from tests.support.fake_spin import FakeSpinPort
from tests.support.fake_workers import FakeWorkers
from tests.support.tui_harness import FakeLock
from tests.support.fake_store import FakeStore
from tests.support.factories import make_step


class FakeContainer:
    def __init__(self, store=None, spin=None, lock=None, drain=None, workers=None):
        self.store = store
        self.spin = spin if spin is not None else FakeSpinPort()
        self.lock = lock if lock is not None else FakeLock(running=False)
        self.drain = drain if drain is not None else FakeDrain()
        self.workers = workers if workers is not None else FakeWorkers()


class _FixedFlowService:
    def __init__(self, phrases):
        self._phrases = phrases

    def display_for(self, node):
        return self._phrases.get(node.stage)


class TestCmdStatusDisplayPhrase(unittest.TestCase):
    def setUp(self):
        self._orig = cli_mod._container
        self.addCleanup(lambda: cli_mod.set_container(self._orig))
        cli_mod.set_container(FakeContainer())

    def _run(self, lanes, flow_service, spin=None):
        store = FakeStore()
        store.create_item("an item", "a description", id="i-1")
        cli_mod.set_container(FakeContainer(store=store, spin=spin))
        fake_resp = mock.Mock(lanes=lanes)
        with mock.patch.object(cli_mod, "StatusUseCase") as UseCase, \
                mock.patch.object(cli_mod, "_flow", lambda: flow_service):
            UseCase.return_value.execute.return_value = fake_resp
            out = io.StringIO()
            with redirect_stdout(out):
                rc = cmd_status([]) or 0
        return rc, out.getvalue()

    def test_shows_the_phrase_and_stage_when_a_phrase_is_declared(self):
        node = make_step(id="t1", title="one", step="code-await-merge")
        lanes = {"inbox": [node], "active": [], "queue": []}
        rc, out = self._run(lanes, _FixedFlowService({"code-await-merge": "Review the PR"}))
        self.assertEqual(rc, 0)
        self.assertIn("Review the PR · code-await-merge", out)

    def test_shows_the_bare_stage_when_no_phrase_is_declared(self):
        node = make_step(id="t1", title="one", step="build")
        lanes = {"inbox": [node], "active": [], "queue": []}
        rc, out = self._run(lanes, _FixedFlowService({}))
        line = next(l for l in out.splitlines() if "t1" in l)
        self.assertTrue(line.endswith("  build"))

    def test_shows_a_death_count_for_a_step_with_a_spin_entry(self):
        node = make_step(id="t1", title="one", step="build")
        lanes = {"inbox": [node], "active": [], "queue": []}
        spin = FakeSpinPort({"steps": {"t1": {"count": 2, "since": 100, "last_line": "x"}}})
        rc, out = self._run(lanes, _FixedFlowService({}), spin=spin)
        line = next(l for l in out.splitlines() if "t1" in l)
        self.assertIn("worker died 2 times", line)

    def test_no_suffix_when_no_spin_entry_is_on_record(self):
        node = make_step(id="t1", title="one", step="build")
        lanes = {"inbox": [node], "active": [], "queue": []}
        rc, out = self._run(lanes, _FixedFlowService({}))
        line = next(l for l in out.splitlines() if "t1" in l)
        self.assertTrue(line.endswith("  build"))


if __name__ == "__main__":
    unittest.main()


class TestCmdStatusDraining(unittest.TestCase):
    def setUp(self):
        self._orig = cli_mod._container
        self.addCleanup(lambda: cli_mod.set_container(self._orig))

    def _run(self, *argv, running=True, requested=True, workers=None):
        store = FakeStore()
        cli_mod.set_container(FakeContainer(
            store=store, lock=FakeLock(running=running), drain=FakeDrain(requested=requested),
            workers=workers,
        ))
        out = io.StringIO()
        with mock.patch.object(cli_mod, "_flow", lambda: _FixedFlowService({})), \
                redirect_stdout(out):
            rc = cmd_status(list(argv))
        return rc, out.getvalue()

    def test_plain_output_starts_with_the_draining_line_and_remaining_count(self):
        workers = FakeWorkers(
            workers=[{"spawnid": "w1", "pid": 1, "started": 0}, {"spawnid": "w2", "pid": 2, "started": 0}],
            alive_pids=(1, 2),
        )
        _rc, out = self._run(workers=workers)
        self.assertEqual(out.splitlines()[0], "pool draining (2 running)")

    def test_plain_output_is_unchanged_when_not_draining(self):
        _rc, draining = self._run()
        _rc, idle = self._run(requested=False)
        self.assertEqual(draining.splitlines()[1:], idle.splitlines())
        self.assertFalse(idle.startswith("pool draining"))

    def test_a_stale_marker_with_no_pool_shows_nothing(self):
        _rc, out = self._run(running=False, requested=True)
        self.assertNotIn("draining", out)

    def test_json_output_is_identical_in_both_states(self):
        _rc, draining = self._run("--json")
        _rc, idle = self._run("--json", requested=False)
        self.assertEqual(draining, idle)
