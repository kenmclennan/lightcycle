import io
import unittest
from contextlib import redirect_stdout, redirect_stderr

from lightcycle import cli
from tests.support.fake_store import FakeStore


def call(fn, *args):
    out, err = io.StringIO(), io.StringIO()
    try:
        with redirect_stdout(out), redirect_stderr(err):
            rc = fn(list(args)) or 0
    except SystemExit as e:
        rc = e.code if isinstance(e.code, int) else 1
    return rc, out.getvalue(), err.getvalue()


class FakeConfig:
    def __init__(self, cap=72):
        self._cap = cap

    def max_title_length(self):
        return self._cap


class FakeContainer:
    def __init__(self, store, cap=72):
        self.store = store
        self.config = FakeConfig(cap=cap)


class TestCmdNewTitleCap(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        self.cap = 10
        cli.set_container(FakeContainer(self.store, cap=self.cap))

    def test_new_item_title_over_cap_is_rejected(self):
        rc, out, err = call(cli.cmd_new, "item", "x" * (self.cap + 1))
        self.assertEqual(rc, 1)
        self.assertIn(str(self.cap), err)
        self.assertIn("--description", err)
        self.assertEqual(self.store.all_nodes(), [])

    def test_new_item_title_at_cap_is_accepted(self):
        rc, out, err = call(cli.cmd_new, "item", "x" * self.cap)
        self.assertEqual(rc, 0)

    def test_new_theme_title_over_cap_is_rejected(self):
        rc, out, err = call(cli.cmd_new, "theme", "x" * (self.cap + 1))
        self.assertEqual(rc, 1)
        self.assertIn(str(self.cap), err)
        self.assertIn("--description", err)
        self.assertEqual(self.store.all_nodes(), [])


class TestCmdSetTitleCap(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        self.cap = 10
        cli.set_container(FakeContainer(self.store, cap=self.cap))
        self.step_id = self.store.create_step("original", role="human")

    def test_set_title_over_cap_is_rejected(self):
        rc, out, err = call(cli.cmd_set, self.step_id, "--title", "x" * (self.cap + 1))
        self.assertEqual(rc, 1)
        self.assertIn(str(self.cap), err)
        self.assertIn("--description", err)
        self.assertEqual(self.store.get_node(self.step_id).title, "original")

    def test_set_title_at_cap_is_accepted(self):
        rc, out, err = call(cli.cmd_set, self.step_id, "--title", "x" * self.cap)
        self.assertEqual(rc, 0)
        self.assertEqual(self.store.get_node(self.step_id).title, "x" * self.cap)

    def test_set_without_title_is_unaffected(self):
        rc, out, err = call(cli.cmd_set, self.step_id, "--description", "d")
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
