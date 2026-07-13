import unittest

from lightcycle.application.services.flow import FlowService
from lightcycle.application.work.file_child_item import FileChildItemInput, FileChildItemUseCase
from tests.support.fake_fs import FakeFs, graph_text_from_metas
from tests.support.fake_store import FakeStore


def _flow(store):
    metas = {
        "coder": {
            "model": "sonnet", "step": "write-code",
            "accepts": {"spec": "required"}, "routes": {"done": "open-pr"},
        },
    }
    workflow = graph_text_from_metas(metas, entry="write-code", requires={"repo"})
    return FlowService(FakeFs(metas, workflow=workflow), store)


class TestFileChildItem(unittest.TestCase):
    def test_files_a_child_item_carrying_spec_and_repo(self):
        s = FakeStore()
        theme = s.create_theme("t")
        spec_item = s.create_item("LC-59: phase c1", theme=theme, project="lightcycle")
        s.add_artifact(spec_item, "spec", "lightcycle/LC-59-phase-c1.md")
        s.add_artifact(spec_item, "repo", "lightcycle")
        s.add_artifact(spec_item, "branch", "spec/LC-59-phase-c1")
        s.add_artifact(spec_item, "pr", "https://github.com/x/y/pull/1")

        resp = FileChildItemUseCase(s, _flow(s)).execute(
            FileChildItemInput(parent=spec_item, workflow="standard", step="write-code")
        )

        child = s.get_node(resp.item)
        self.assertEqual(child.type, "item")
        self.assertEqual(child.parent, theme)
        self.assertEqual(child.theme, theme)
        self.assertEqual(child.project, "lightcycle")
        self.assertEqual(child.workflow, "standard")

        artifacts = {a.type: a.value for a in s.item_artifacts(resp.item)}
        self.assertEqual(artifacts, {
            "filed-from": spec_item,
            "spec": "lightcycle/LC-59-phase-c1.md",
            "repo": "lightcycle",
        })

        step = s.get_node(resp.step)
        self.assertEqual(step.type, "step")
        self.assertEqual(step.step, "write-code")
        self.assertEqual(step.parent, resp.item)

    def test_child_title_matches_the_parent(self):
        s = FakeStore()
        spec_item = s.create_item("LC-59: phase c1", theme=s.create_theme("t"), project="lightcycle")
        s.add_artifact(spec_item, "repo", "lightcycle")
        s.add_artifact(spec_item, "spec", "lightcycle/LC-59-phase-c1.md")

        resp = FileChildItemUseCase(s, _flow(s)).execute(
            FileChildItemInput(parent=spec_item, workflow="standard", step="write-code")
        )

        self.assertEqual(s.get_node(resp.item).title, "LC-59: phase c1")


if __name__ == "__main__":
    unittest.main()
