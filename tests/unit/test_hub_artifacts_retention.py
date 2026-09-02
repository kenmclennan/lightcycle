import unittest

from lightcycle.adapters.tui.hub import NodeHubScreen
from tests.support.fake_store import FakeStore
from tests.support.tui_harness import launch, make_test_container


class TestHubArtifactsShapeRetention(unittest.TestCase):
    def _launch(self, store):
        session = launch(make_test_container(store=store))
        self.addCleanup(session.close)
        return session

    def _push_hub(self, session, node_id):
        session.run(
            lambda: session.app.push_screen(
                NodeHubScreen(session.app.container, node_id, session.app._now)
            )
        )
        session.pause()
        return session.app.screen

    def test_last_artifacts_shape_is_reassigned_on_the_cheap_update_path(self):
        store = FakeStore()
        item = store.create_item("item", "a description")
        store.add_artifact(item, "repo", "kenmclennan/lightcycle")

        session = self._launch(store)
        screen = self._push_hub(session, item)

        first_shape = screen._last_artifacts_shape
        self.assertIsNotNone(first_shape)

        session.run(screen.poll_refresh)
        session.pause()

        second_shape = screen._last_artifacts_shape
        self.assertEqual(second_shape, first_shape)
        self.assertIsNot(second_shape, first_shape)


if __name__ == "__main__":
    unittest.main()
