import unittest

from lightcycle.application.errors import UseCaseError
from lightcycle.application.work.create_item import CreateItemInput, CreateItemUseCase
from tests.support.fake_store import FakeStore
from tests.support.step_factory import create_owned_step


def _store_with_app():
    store = FakeStore()
    store.add_project("acme/app", shortcode="APP")
    return store


class TestCreateItemUseCase(unittest.TestCase):
    def test_happy_path_returns_id_and_creates_a_backlogged_item(self):
        store = _store_with_app()
        b1 = create_owned_step(store, "backlog one", role="human")
        resp = CreateItemUseCase(store).execute(
            CreateItemInput(title="an item", description="a description", project="app", backlog=[b1])
        )
        self.assertEqual(store.get_node(resp.id).state, "backlogged")
        self.assertEqual(
            [(a.type, a.value) for a in store.item_artifacts(resp.id)], [("resolves", b1)]
        )

    def test_a_successful_create_no_longer_reports_a_defaulted_flag(self):
        store = _store_with_app()
        resp = CreateItemUseCase(store).execute(
            CreateItemInput(title="an item", description="a description", project="app")
        )
        self.assertFalse(hasattr(resp, "defaulted"))

    def test_repo_attaches_a_repo_artifact(self):
        store = FakeStore()
        store.add_project("acme/lightcycle", shortcode="LC")
        resp = CreateItemUseCase(store).execute(
            CreateItemInput(title="an item", description="a description", repo="lightcycle")
        )
        self.assertEqual(store.get_item(resp.id).repo, "lightcycle")

    def test_multiple_backlog_ids_link_in_order(self):
        store = _store_with_app()
        b1 = create_owned_step(store, "backlog one", role="human")
        b2 = create_owned_step(store, "backlog two", role="human")
        resp = CreateItemUseCase(store).execute(
            CreateItemInput(
                title="an item", description="a description", project="app", backlog=[b1, b2]
            )
        )
        self.assertEqual(
            [(a.type, a.value) for a in store.item_artifacts(resp.id)],
            [("resolves", b1), ("resolves", b2)],
        )

    def _refused(self, store, **fields):
        with self.assertRaises(UseCaseError) as ctx:
            CreateItemUseCase(store).execute(
                CreateItemInput(title="an item", description="a description", **fields)
            )
        return str(ctx.exception)

    def test_unregistered_project_raises_naming_the_project_and_creates_nothing(self):
        store = FakeStore()
        self.assertIn("ghost/repo", self._refused(store, project="ghost/repo"))
        self.assertEqual(store.all_nodes(), [])

    def test_ambiguous_project_raises_and_creates_nothing(self):
        store = FakeStore()
        store.add_project("acme/app", shortcode="ACME")
        store.add_project("other/app", shortcode="OTHER")
        self.assertIn("app", self._refused(store, project="app"))
        self.assertEqual(store.all_nodes(), [])

    def test_shortcodeless_project_raises_and_creates_nothing(self):
        store = FakeStore()
        store.add_project("acme/ghost", local_path="/x")
        self.assertIn("acme/ghost", self._refused(store, project="acme/ghost"))
        self.assertEqual(store.all_nodes(), [])

    def test_neither_project_nor_repo_raises_and_creates_nothing(self):
        store = FakeStore()
        self._refused(store)
        self.assertEqual(store.all_nodes(), [])

    def test_unregistered_repo_raises_and_creates_no_node_or_repo_artifact(self):
        store = FakeStore()
        self.assertIn("ghost/repo", self._refused(store, repo="ghost/repo"))
        self.assertEqual(store.all_nodes(), [])

    def test_shortcodeless_repo_raises_and_creates_nothing(self):
        store = FakeStore()
        store.add_project("acme/ghost", local_path="/x")
        self.assertIn("registered but has no shortcode", self._refused(store, repo="acme/ghost"))
        self.assertEqual(store.all_nodes(), [])

    def test_registered_repo_with_no_project_derives_shortcode_and_project(self):
        store = FakeStore()
        store.add_project("kenmclennan/lightcycle", shortcode="LC")
        resp = CreateItemUseCase(store).execute(
            CreateItemInput(
                title="an item", description="a description", repo="kenmclennan/lightcycle"
            )
        )
        self.assertTrue(resp.id.startswith("LC-"))
        self.assertEqual(store.get_item(resp.id).project, "lightcycle")

    def test_explicit_project_wins_over_a_different_registered_repo(self):
        store = FakeStore()
        store.add_project("acme/app", shortcode="ACME")
        store.add_project("kenmclennan/lightcycle", shortcode="LC")
        resp = CreateItemUseCase(store).execute(
            CreateItemInput(
                title="an item", description="a description",
                project="acme/app", repo="kenmclennan/lightcycle",
            )
        )
        self.assertEqual(store.get_item(resp.id).project, "acme/app")


if __name__ == "__main__":
    unittest.main()
