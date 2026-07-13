import unittest

from lightcycle.application.services.flow import FlowService
from lightcycle.application.work.transition_item import (
    TransitionItemInput,
    TransitionItemUseCase,
)
from tests.support.fake_fs import FakeFs, graph_text_from_metas
from tests.support.fake_store import FakeStore


class FakeWorktrees:
    def __init__(self, store=None):
        self.removed = []
        self._store = store

    def remove(self, item):
        self.removed.append(item)
        if self._store is not None:
            self.workflow_at_removal = self._store.get_node(item).workflow


def _flow(store):
    metas = {
        "coder": {
            "model": "sonnet", "step": "write-code",
            "accepts": {"spec": "required"}, "routes": {"done": "open-pr"},
        },
    }
    workflow = graph_text_from_metas(metas, entry="write-code", requires={"repo"})
    return FlowService(FakeFs(metas, workflow=workflow), store)


class TestTransitionItem(unittest.TestCase):
    def _setup(self):
        s = FakeStore()
        theme = s.create_theme("t")
        item = s.create_item("LC-71: same-item transition", theme=theme, workflow="spec")
        s.add_artifact(item, "spec", "lightcycle/LC-71-same-item.md")
        s.add_artifact(item, "repo", "lightcycle")
        spec_step = s.create_step(
            "spec-writer: LC-71", step="spec-writer", role="spec-writer", parent=item
        )
        s.close(spec_step, "done")
        awaiting = s.create_step(
            "await-merge: LC-71", step="await-merge", role="human", parent=item
        )
        return s, theme, item, awaiting

    def test_files_a_write_code_step_on_the_same_item(self):
        s, theme, item, awaiting = self._setup()
        worktrees = FakeWorktrees()

        resp = TransitionItemUseCase(s, _flow(s), worktrees).execute(
            TransitionItemInput(item=item, outcome="spec-merged", workflow="standard", step="write-code")
        )

        self.assertEqual(resp.item, item)
        step = s.get_node(resp.step)
        self.assertEqual(step.type, "step")
        self.assertEqual(step.step, "write-code")
        self.assertEqual(step.parent, item)

    def test_item_keeps_its_id_spec_and_repo(self):
        s, theme, item, awaiting = self._setup()
        worktrees = FakeWorktrees()

        TransitionItemUseCase(s, _flow(s), worktrees).execute(
            TransitionItemInput(item=item, outcome="spec-merged", workflow="standard", step="write-code")
        )

        node = s.get_node(item)
        self.assertEqual(node.id, item)
        self.assertEqual(node.workflow, "standard")
        artifacts = {a.type: a.value for a in s.item_artifacts(item)}
        self.assertEqual(artifacts["spec"], "lightcycle/LC-71-same-item.md")
        self.assertEqual(artifacts["repo"], "lightcycle")
        self.assertNotIn("filed-from", artifacts)

    def test_no_child_item_is_created(self):
        s, theme, item, awaiting = self._setup()
        worktrees = FakeWorktrees()
        before = {n.id for n in s.all_nodes() if n.type == "item"}

        TransitionItemUseCase(s, _flow(s), worktrees).execute(
            TransitionItemInput(item=item, outcome="spec-merged", workflow="standard", step="write-code")
        )

        after = {n.id for n in s.all_nodes() if n.type == "item"}
        self.assertEqual(after, before)

    def test_item_stays_in_progress(self):
        s, theme, item, awaiting = self._setup()
        worktrees = FakeWorktrees()

        TransitionItemUseCase(s, _flow(s), worktrees).execute(
            TransitionItemInput(item=item, outcome="spec-merged", workflow="standard", step="write-code")
        )

        self.assertEqual(s.get_node(item).state, "in_progress")

    def test_closes_the_not_done_await_merge_step_with_the_outcome(self):
        s, theme, item, awaiting = self._setup()
        worktrees = FakeWorktrees()

        TransitionItemUseCase(s, _flow(s), worktrees).execute(
            TransitionItemInput(item=item, outcome="spec-merged", workflow="standard", step="write-code")
        )

        closed = s.get_node(awaiting)
        self.assertEqual(closed.state, "done")
        self.assertEqual(closed.outcome, "spec-merged")

    def test_removes_the_worktree_while_workflow_is_still_the_source_one(self):
        s, theme, item, awaiting = self._setup()
        worktrees = FakeWorktrees(store=s)

        TransitionItemUseCase(s, _flow(s), worktrees).execute(
            TransitionItemInput(item=item, outcome="spec-merged", workflow="standard", step="write-code")
        )

        self.assertEqual(worktrees.removed, [item])
        self.assertEqual(worktrees.workflow_at_removal, "spec")


if __name__ == "__main__":
    unittest.main()
