import io
import unittest
from contextlib import redirect_stdout

from lightcycle import cli
from lightcycle.ports.store import NodeNotFoundError
from tests.support.fake_store import FakeStore


class FakeConfig:
    def max_title_length(self):
        return 72


class FakeContainer:
    def __init__(self, store):
        self.store = store
        self.config = FakeConfig()


def call(fn, *args):
    out = io.StringIO()
    with redirect_stdout(out):
        rc = fn(list(args)) or 0
    return rc, out.getvalue()


class TestCmdQueueTitleComposition(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        cli.set_container(FakeContainer(self.store))

    def test_a_queued_step_with_a_resolvable_item_shows_stage_and_item_title(self):
        item = self.store.create_item("fix the thing", "a description")
        self.store.create_step(step="build", role="agent", parent=item)
        rc, out = call(cli.cmd_queue, "5")
        self.assertEqual(rc, 0)
        self.assertIn("build: fix the thing", out)

    def test_a_queued_step_whose_item_cannot_be_resolved_falls_back_to_the_bare_stage(self):
        item = self.store.create_item("temporary", "a description")
        self.store.create_step(step="build", role="agent", parent=item)
        real_get_node = self.store.get_node

        def _unresolvable(tid):
            if tid == item:
                raise NodeNotFoundError("gone")
            return real_get_node(tid)

        self.store.get_node = _unresolvable
        rc, out = call(cli.cmd_queue, "5")
        self.assertEqual(rc, 0)
        self.assertNotIn("fix the thing", out)
        line = next(l for l in out.splitlines() if l.strip())
        self.assertTrue(line.rstrip().endswith("build"))


if __name__ == "__main__":
    unittest.main()
