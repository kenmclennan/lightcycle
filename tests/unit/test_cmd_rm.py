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


class FakeWorkers:
    def workers_state(self):
        return []

    def pid_alive(self, pid, started=None):
        return False


class FakeContainer:
    def __init__(self, store):
        self.store = store
        self.workers = FakeWorkers()
        self.git = None
        self.fs = None
        self.config = None


class TestCmdRm(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        cli.set_container(FakeContainer(self.store))

    def test_force_flag_parses_and_delegates_to_the_use_case(self):
        step = self.store.create_step("orphan build", role="coder")
        rc, out, err = call(cli.cmd_rm, step, "--force")
        self.assertEqual(rc, 0)
        self.assertIn(step, out)
        with self.assertRaises(KeyError):
            self.store.get_node(step)

    def test_renders_the_refusal_and_leaves_the_node(self):
        theme = self.store.create_theme("theme")
        self.store.create_item("child", theme=theme)
        rc, out, err = call(cli.cmd_rm, theme)
        self.assertNotEqual(rc, 0)
        self.assertIn(theme, err)
        self.assertEqual(self.store.get_node(theme).id, theme)


if __name__ == "__main__":
    unittest.main()
