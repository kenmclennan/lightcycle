import unittest

from lightcycle.application.pool.note_draft_prs import NoteDraftPrsUseCase
from lightcycle.application.pool.pr_sync_reads import PrSyncReads
from tests.support.fake_fs import flow_from_metas
from tests.support.fake_github import FakeGitHub
from tests.support.fake_store import FakeStore
from tests.support.stacked import STACK_URL, build_stack, layer_url
from tests.unit.test_dispatch_pr_feedback import _FlowAdapter, plant_pr

_FLOW = flow_from_metas({
    "watcher": {
        "model": "sonnet", "step": "watch-step",
        "routes": {"merged": "done-step"}, "on_pr_merge": "merged",
    },
})

_SINGLE = "https://github.com/acme/widget/pull/9"


class _Failing(FakeGitHub):
    def __init__(self, failing=(), **kw):
        super().__init__(**kw)
        self.failing = set(failing)

    def pr_sync_state(self, pr):
        if pr in self.failing:
            from lightcycle.ports.github import ReadFailure
            return ReadFailure(1, "boom")
        return super().pr_sync_state(pr)


class _Rig:
    def __init__(self, drafts=(), stacked=True, failing=()):
        self.layers = build_stack(3)
        self.github = _Failing(
            failing=failing, draft_prs=drafts, stacks={STACK_URL: self.layers})
        self.store = FakeStore()
        self.item = self.store.create_item("feature", "d")
        if stacked:
            rid = plant_pr(self.store, self.item, self.layers[-1].url)
            self.store.set_stack(rid, STACK_URL)
        else:
            plant_pr(self.store, self.item, _SINGLE)
        self.step = self.store.create_step(stage="watch-step", role="agent", item=self.item)
        self.uc = NoteDraftPrsUseCase(self.store, self.github, _FlowAdapter(_FLOW))

    def run(self):
        return self.uc.execute(PrSyncReads(self.github))

    def lines(self):
        notes = self.store.get_node(self.step).notes or ""
        return [l for l in notes.splitlines() if l.startswith("draft-pr:")]


class TestNoteDraftPrs(unittest.TestCase):
    def test_a_draft_layer_is_noted_on_the_gate(self):
        rig = _Rig(drafts={layer_url(2)})

        rig.run()

        (line,) = rig.lines()
        self.assertIn("layer 2 of 3", line)
        self.assertIn(layer_url(2), line)
        self.assertNotIn("layer 1 of 3", line)
        self.assertNotIn("layer 3 of 3", line)
        self.assertNotEqual(rig.store.get_node(rig.step).state, "done")

    def test_two_draft_layers_give_one_note_naming_both(self):
        rig = _Rig(drafts={layer_url(1), layer_url(3)})

        rig.run()

        (line,) = rig.lines()
        self.assertIn("layer 1 of 3", line)
        self.assertIn("layer 3 of 3", line)

    def test_the_note_clears_when_the_layer_is_ready(self):
        rig = _Rig(drafts={layer_url(2)})
        rig.run()
        self.assertEqual(len(rig.lines()), 1)

        rig.github._draft_prs.clear()
        rig.run()

        self.assertEqual(rig.lines(), [])

    def test_a_draft_single_pr_is_noted(self):
        rig = _Rig(drafts={_SINGLE}, stacked=False)

        rig.run()

        (line,) = rig.lines()
        self.assertIn(_SINGLE, line)

    def test_an_unread_layer_leaves_the_note_alone(self):
        rig = _Rig(drafts={layer_url(2)})
        rig.run()
        rig.github.failing = {layer_url(1)}

        rig.run()

        self.assertEqual(len(rig.lines()), 1)

    def test_the_same_draft_is_not_noted_twice(self):
        rig = _Rig(drafts={layer_url(2)})

        rig.run()
        rig.run()

        (line,) = rig.lines()
        self.assertNotIn("x2", line)

    def test_no_gate_hold_is_placed(self):
        rig = _Rig(drafts={layer_url(2)})

        rig.run()

        self.assertEqual(
            [a for a in rig.store.item_artifacts(rig.step) if a.type == "gate-hold"], [])
