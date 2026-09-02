import unittest

from lightcycle.application.errors import UseCaseError
from lightcycle.application.work.resolve_backlog import link_resolves, retire_resolved
from tests.support.fake_store import FakeStore


class TestLinkResolves(unittest.TestCase):
    def test_adds_one_resolves_artifact_per_id_in_order(self):
        s = FakeStore()
        owner = s.create_item("an item", "a description")
        b1 = s.create_step("backlog one", role="human")
        b2 = s.create_step("backlog two", role="human")
        link_resolves(s, owner, [b1, b2])
        arts = s.item_artifacts(owner)
        self.assertEqual([(a.type, a.value) for a in arts], [("resolves", b1), ("resolves", b2)])

    def test_unknown_id_raises_and_writes_no_artifacts(self):
        s = FakeStore()
        owner = s.create_item("an item", "a description")
        b1 = s.create_step("backlog one", role="human")
        with self.assertRaises(UseCaseError) as ctx:
            link_resolves(s, owner, [b1, "does-not-exist"])
        self.assertIn("does-not-exist", str(ctx.exception))
        self.assertEqual(s.item_artifacts(owner), [])

    def test_resolves_artifact_is_internal(self):
        s = FakeStore()
        owner = s.create_item("an item", "a description")
        b1 = s.create_step("backlog one", role="human")
        link_resolves(s, owner, [b1])
        self.assertTrue(s.item_artifacts(owner)[0].internal)


class TestRetireResolved(unittest.TestCase):
    def test_closes_every_linked_backlog_item_not_already_done(self):
        s = FakeStore()
        owner = s.create_item("an item", "a description")
        b1 = s.create_step("backlog one", role="human")
        b2 = s.create_step("backlog two", role="human")
        link_resolves(s, owner, [b1, b2])
        retire_resolved(s, owner)
        self.assertEqual(s.get_node(b1).state, "done")
        self.assertEqual(s.get_node(b2).state, "done")
        self.assertEqual(
            [(a.type, a.value) for a in s.item_artifacts(b1)], [("resolved-by", owner)]
        )
        self.assertEqual(
            [(a.type, a.value) for a in s.item_artifacts(b2)], [("resolved-by", owner)]
        )

    def test_resolved_by_artifact_is_internal(self):
        s = FakeStore()
        owner = s.create_item("an item", "a description")
        b1 = s.create_step("backlog one", role="human")
        link_resolves(s, owner, [b1])
        retire_resolved(s, owner)
        self.assertTrue(s.item_artifacts(b1)[0].internal)

    def test_already_done_backlog_item_is_left_alone(self):
        s = FakeStore()
        owner = s.create_item("an item", "a description")
        b1 = s.create_step("backlog one", role="human")
        link_resolves(s, owner, [b1])
        s.close(b1, "already handled")
        retire_resolved(s, owner)
        self.assertEqual(s.get_node(b1).outcome, "already handled")
        self.assertEqual(s.item_artifacts(b1), [])

    def test_no_resolves_links_is_a_no_op(self):
        s = FakeStore()
        owner = s.create_item("an item", "a description")
        retire_resolved(s, owner)
        self.assertEqual(s.item_artifacts(owner), [])


if __name__ == "__main__":
    unittest.main()
