import io
import unittest
from contextlib import redirect_stderr, redirect_stdout

import lightcycle.cli as cli
from tests.support.harness import Harness


class TestCliPrimitives(unittest.TestCase):
    def setUp(self):
        self.h = Harness(["coder", "reviewer"])

    def _run(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = getattr(cli, "cmd_" + args[0].replace("-", "_"))(
                [str(a) for a in args[1:]]
            ) or 0
        return rc, out.getvalue().strip(), err.getvalue().strip()

    def test_new_item_is_a_todo(self):
        rc, item, _ = self._run("new", "item", "add refunds")
        self.assertEqual(rc, 0)
        node = self.h.store.get_node(item)
        self.assertEqual(node.type, "item")
        self.assertEqual(node.state, "backlogged")

    def test_new_rejects_an_unknown_type(self):
        rc, _, err = self._run("new", "widget", "x")
        self.assertEqual(rc, 2)
        self.assertIn("theme | item | step", err)

    def test_set_state_active_activates_the_item(self):
        _, item, _ = self._run("new", "item", "add refunds")
        rc, step, _ = self._run("set", item, "--state", "active", "--workflow", "standard")
        self.assertEqual(rc, 0)
        self.assertEqual(self.h.store.get_node(item).state, "ready")
        self.assertEqual(self.h.store.get_node(step).step, "build")

    def test_set_parent_moves_the_item_under_a_theme(self):
        _, theme, _ = self._run("new", "theme", "payments")
        _, item, _ = self._run("new", "item", "refunds")
        self._run("set", item, "--parent", theme)
        self.assertEqual(self.h.store.get_node(item).theme, theme)

    def test_attach_records_an_artifact(self):
        _, item, _ = self._run("new", "item", "x")
        self._run("attach", item, "spec", "specs/x.md")
        arts = self.h.store.item_artifacts(item)
        self.assertTrue(any(a.type == "spec" and a.value == "specs/x.md" for a in arts))

    def test_dep_links_a_blocker(self):
        _, a, _ = self._run("new", "item", "a")
        _, b, _ = self._run("new", "item", "b")
        rc, _, _ = self._run("dep", a, "--needs", b)
        self.assertEqual(rc, 0)

    def test_rm_deletes_a_node(self):
        _, item, _ = self._run("new", "item", "gone")
        self._run("rm", item)
        with self.assertRaises(KeyError):
            self.h.store.get_node(item)


if __name__ == "__main__":
    unittest.main()
