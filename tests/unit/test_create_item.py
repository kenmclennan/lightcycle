import unittest

from lightcycle.application.errors import UseCaseError
from lightcycle.application.work.create_item import CreateItemInput, CreateItemUseCase
from tests.support.fake_store import FakeStore
from tests.support.step_factory import create_owned_step


class FakeConfig:
    def __init__(self, shortcode="XY"):
        self._shortcode = shortcode

    def shortcode(self):
        return self._shortcode


class TestCreateItemUseCase(unittest.TestCase):
    def test_happy_path_returns_id_and_creates_a_backlogged_item(self):
        store = FakeStore()
        b1 = create_owned_step(store, "backlog one", role="human")
        resp = CreateItemUseCase(store, FakeConfig()).execute(
            CreateItemInput(title="an item", description="a description", backlog=[b1])
        )
        self.assertEqual(store.get_node(resp.id).state, "backlogged")
        self.assertEqual(
            [(a.type, a.value) for a in store.item_artifacts(resp.id)], [("resolves", b1)]
        )

    def test_repo_attaches_a_repo_artifact(self):
        store = FakeStore()
        resp = CreateItemUseCase(store, FakeConfig()).execute(
            CreateItemInput(title="an item", description="a description", repo="lightcycle")
        )
        self.assertEqual(store.get_item(resp.id).repo, "lightcycle")

    def test_multiple_backlog_ids_link_in_order(self):
        store = FakeStore()
        b1 = create_owned_step(store, "backlog one", role="human")
        b2 = create_owned_step(store, "backlog two", role="human")
        resp = CreateItemUseCase(store, FakeConfig()).execute(
            CreateItemInput(title="an item", description="a description", backlog=[b1, b2])
        )
        self.assertEqual(
            [(a.type, a.value) for a in store.item_artifacts(resp.id)],
            [("resolves", b1), ("resolves", b2)],
        )

    def test_unregistered_project_raises_naming_the_project_and_creates_nothing(self):
        store = FakeStore()
        with self.assertRaises(UseCaseError) as ctx:
            CreateItemUseCase(store, FakeConfig()).execute(
                CreateItemInput(
                    title="an item", description="a description", project="ghost/repo"
                )
            )
        self.assertIn("ghost/repo", str(ctx.exception))
        self.assertEqual(store.all_nodes(), [])

    def test_ambiguous_project_raises_and_creates_nothing(self):
        store = FakeStore()
        store.add_project("acme/app", shortcode="ACME")
        store.add_project("other/app", shortcode="OTHER")
        with self.assertRaises(UseCaseError) as ctx:
            CreateItemUseCase(store, FakeConfig()).execute(
                CreateItemInput(title="an item", description="a description", project="app")
            )
        self.assertIn("app", str(ctx.exception))
        self.assertEqual(store.all_nodes(), [])

    def test_shortcodeless_project_raises_and_creates_nothing(self):
        store = FakeStore()
        store.add_project("acme/ghost", local_path="/x")
        with self.assertRaises(UseCaseError) as ctx:
            CreateItemUseCase(store, FakeConfig()).execute(
                CreateItemInput(
                    title="an item", description="a description", project="acme/ghost"
                )
            )
        self.assertIn("acme/ghost", str(ctx.exception))
        self.assertEqual(store.all_nodes(), [])


if __name__ == "__main__":
    unittest.main()
