import unittest
from types import SimpleNamespace

from lightcycle.domain.work.open_successors import open_successors


def _s(sid, previous, state):
    return SimpleNamespace(id=sid, previous_step=previous, state=state)


class TestOpenSuccessors(unittest.TestCase):
    def test_no_successor_returns_empty(self):
        self.assertEqual(open_successors("a", [_s("a", None, "done")]), [])

    def test_one_open_successor_is_returned(self):
        self.assertEqual(open_successors("a", [_s("b", "a", "queued")]), ["b"])

    def test_a_done_successor_is_ignored(self):
        siblings = [_s("b", "a", "done"), _s("c", "a", "running")]
        self.assertEqual(open_successors("a", siblings), ["c"])

    def test_a_waiting_successor_counts_as_open(self):
        self.assertEqual(open_successors("a", [_s("b", "a", "waiting")]), ["b"])

    def test_a_step_whose_previous_is_another_step_is_ignored(self):
        self.assertEqual(open_successors("a", [_s("c", "b", "queued")]), [])

    def test_a_done_step_whose_only_successor_is_closed_returns_empty(self):
        self.assertEqual(open_successors("a", [_s("b", "a", "done")]), [])


if __name__ == "__main__":
    unittest.main()
