import unittest

from lightcycle.application.pool import TailSessionsInput, TailSessionsUseCase
from tests.support.fake_fs import FakeFs
from tests.support.fake_store import FakeStore


def _step_with_logs(*paths):
    store = FakeStore()
    item = store.create_item("Item", "d")
    step = store.create_step(stage="coder", role="agent", item=item)
    for path in paths:
        store.set_log(step, path)
    return store, step


def _run(store, fs, target):
    return TailSessionsUseCase(store, fs, fs).execute(TailSessionsInput(target=target, max_bytes=1000))


class TestTailSessions(unittest.TestCase):
    def test_a_step_with_one_session_returns_nothing(self):
        store, step = _step_with_logs("/l/a.log")

        self.assertEqual(_run(store, FakeFs(files={"/l/a.log": b"x\n"}), step), [])

    def test_a_target_that_is_not_a_step_returns_nothing(self):
        store, step = _step_with_logs("/l/a.log", "/l/b.log")
        item = store.get_node(step).item

        self.assertEqual(_run(store, FakeFs(), item), [])
        self.assertEqual(_run(store, FakeFs(), "nope"), [])

    def test_a_mixed_set_of_present_and_missing_logs_reports_each(self):
        store, step = _step_with_logs("/l/a.log", "/l/b.log", "/l/c.log")
        fs = FakeFs(files={"/l/b.log": b"bee\n", "/l/c.log": b"sea\n"})

        tails = _run(store, fs, step)

        self.assertEqual([t.session.log_path for t in tails], ["/l/a.log", "/l/b.log"])
        self.assertEqual([t.exists for t in tails], [False, True])
        self.assertEqual([t.data for t in tails], [b"", b"bee\n"])
