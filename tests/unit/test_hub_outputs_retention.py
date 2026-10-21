import unittest

from lightcycle.adapters.tui.hub import NodeHubScreen, TextArtifactViewerScreen
from tests.support.fake_fs import FakeFs
from tests.support.fake_store import FakeStore
from tests.support.tui_harness import launch, make_test_container


class TestHubOutputsShapeRetention(unittest.TestCase):
    def _push_hub(self, session, node_id):
        session.run(
            lambda: session.app.push_screen(
                NodeHubScreen(session.app.container, node_id, session.app._now)
            )
        )
        session.pause()
        return session.app.screen

    def test_last_outputs_shape_is_reassigned_on_the_cheap_update_path(self):
        store = FakeStore()
        item = store.create_item("item", "a description")
        store.add_artifact(item, "spec", "specs/x.md")

        session = launch(make_test_container(store=store))
        self.addCleanup(session.close)
        screen = self._push_hub(session, item)

        first_shape = screen._last_outputs_shape
        self.assertIsNotNone(first_shape)

        session.run(screen.poll_refresh)
        session.pause()

        second_shape = screen._last_outputs_shape
        self.assertEqual(second_shape, first_shape)
        self.assertIsNot(second_shape, first_shape)

    def test_step_output_is_listed_by_name_with_its_step_and_opens_its_text(self):
        store = FakeStore()
        item = store.create_item("item", "a description", workflow="o/w@abc")
        step = store.create_step(stage="audit", role="agent", item=item)
        store.add_artifact(step, "findings", "the audit digest")
        store.add_artifact(step, "reflection", "private note", internal=True)

        session = launch(make_test_container(store=store, workflow_bundle=FakeFs(
            metas={"auditor": {
                "model": "sonnet", "step": "audit", "produces": {"findings": "optional"}}})))
        self.addCleanup(session.close)
        screen = self._push_hub(session, item)

        self.assertEqual(
            [(line.name, line.step) for line in screen._last_outputs], [("findings", step)]
        )

        session.run(lambda: screen._open_selected_output("0"))
        session.pause()

        self.assertIsInstance(session.app.screen, TextArtifactViewerScreen)
        self.assertEqual(session.app.screen._artifact.value, "the audit digest")

    def test_expansion_survives_a_poll(self):
        store = FakeStore()
        item = store.create_item("item", "a description", workflow="o/w@abc")
        for n, value in enumerate(("specs/v1.md", "specs/v2.md"), start=1):
            pid = store.open_pass(item)
            step = store.create_step(stage="spec", role="agent", item=item)
            store.set_step_pass(step, pid)
            store.add_artifact(step, "spec", value)

        session = launch(make_test_container(store=store, workflow_bundle=FakeFs(
            metas={"w": {"model": "sonnet", "step": "spec", "produces": {"spec": "optional"}}})))
        self.addCleanup(session.close)
        screen = self._push_hub(session, item)
        self.assertEqual(len(screen._last_outputs), 1)

        session.run(screen.toggle_output_history)
        session.pause()
        self.assertEqual(len(screen._last_outputs), 2)

        session.run(screen.poll_refresh)
        session.pause()
        self.assertEqual(len(screen._last_outputs), 2)
        self.assertTrue(screen._last_outputs[1].is_history)


if __name__ == "__main__":
    unittest.main()
