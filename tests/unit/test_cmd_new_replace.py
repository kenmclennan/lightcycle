import unittest

from tests.support.harness import DEFAULT_WORKFLOW, Harness


def _activated(h):
    item = h.store.create_item("an item", "a description")
    rc, out, err = h.run(
        "set", item, "--state", "active", "--workflow", DEFAULT_WORKFLOW, "--step", "build"
    )
    assert rc == 0, err
    return item, out.strip()


class TestCmdNewReplace(unittest.TestCase):
    def setUp(self):
        self.h = Harness(["coder", "reviewer"])

    def test_replace_on_an_item_exits_2_naming_both(self):
        before = list(self.h.store.item_texts())
        rc, out, err = self.h.run(
            "new", "item", "a title", "--description", "d", "--replace", "X"
        )
        self.assertEqual(rc, 2)
        self.assertIn("--replace belongs to a step, not an item", err)
        self.assertEqual(list(self.h.store.item_texts()), before)

    def test_replace_flag_reaches_the_use_case(self):
        item, old = _activated(self.h)
        rc, out, err = self.h.run(
            "new", "step", "", "--parent", item, "--step", "build", "--replace", old
        )
        self.assertEqual(rc, 0, err)
        new = out.strip()
        self.assertNotEqual(new, old)
        ids = [t.id for t in self.h.store.all_steps_including_done()]
        self.assertNotIn(old, ids)
        self.assertIn(new, ids)
