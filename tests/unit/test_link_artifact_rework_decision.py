import json
import unittest

from lightcycle.application.errors import UseCaseError
from lightcycle.application.work.link_artifact import LinkArtifactInput, LinkArtifactUseCase
from lightcycle.domain.work import State
from tests.support.fake_fs import flow_from_metas
from tests.support.fake_github import FakeGitHub
from tests.support.fake_store import FakeStore

_FLOW = flow_from_metas(
    {
        "gate": {
            "step": "gate",
            "routes": {"merged": "cleanup"},
            "on_pr_merge": "merged",
            "on_pr_feedback": "handle-feedback",
        },
        "handle-feedback": {"step": "handle-feedback", "routes": {"rework": "build"}},
    }
)


class _Flow:
    def flow_for(self, node):
        return _FLOW


class TestReworkDecisionAttach(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        self.item = self.store.create_item("t", "d")
        self.step = self._step("handle-feedback", State.RUNNING)
        self.use = LinkArtifactUseCase(self.store, FakeGitHub(), flow=_Flow())

    def _step(self, stage, state):
        step = self.store.create_step(stage=stage, role="agent", item=self.item)
        if state == State.RUNNING:
            self.store.assign(step, "w1")
        else:
            self.store.complete_node(step, "done")
        return step

    def _attach(self, value, target=None, label="inline:1", **kw):
        self.use.execute(LinkArtifactInput(
            item=target or self.step, atype="rework-decision", value=value, label=label, **kw))

    def _refused(self, value, target=None, label="inline:1", **kw):
        with self.assertRaises(UseCaseError) as cm:
            self._attach(value, target, label, **kw)
        return str(cm.exception)

    def _records(self):
        return [a for a in self.store.item_artifacts(self.step) if a.type == "rework-decision"]

    def test_accepts_valid_inline_and_whole_round_values(self):
        self._attach(json.dumps({"sha": "abc", "path": "a/b.py"}), label="inline:1")
        self._attach(json.dumps({"sha": "abc"}), label="mention:2")

        by_label = {r.label: r for r in self._records()}
        self.assertEqual(json.loads(by_label["inline:1"].value), {"sha": "abc", "path": "a/b.py"})
        self.assertEqual(json.loads(by_label["mention:2"].value), {"sha": "abc"})
        self.assertTrue(all(r.internal for r in by_label.values()))

    def test_refuses_invalid_rework_decision_attaches(self):
        good = json.dumps({"sha": "abc"})
        cases = {
            "non-step id": (good, self.item, "inline:1"),
            "unknown id": (good, "NOPE-9", "inline:1"),
            "other stage": (good, self._step("build", State.RUNNING), "inline:1"),
            "not running": (good, self._step("handle-feedback", State.DONE), "inline:1"),
            "empty label": (good, None, ""),
            "malformed json": ("{not json", None, "inline:1"),
            "not an object": ("[1]", None, "inline:1"),
            "missing sha": (json.dumps({"path": "a.py"}), None, "inline:1"),
            "empty sha": (json.dumps({"sha": ""}), None, "inline:1"),
            "extra key": (json.dumps({"sha": "abc", "why": "x"}), None, "inline:1"),
            "empty path": (json.dumps({"sha": "abc", "path": ""}), None, "inline:1"),
        }
        for name, (value, target, label) in cases.items():
            with self.subTest(name):
                self._refused(value, target, label)
        self.assertEqual(self._records(), [])

    def test_a_repeated_label_needs_replace(self):
        self._attach(json.dumps({"sha": "abc"}))

        self.assertIn("--replace", self._refused(json.dumps({"sha": "def"})))

        self._attach(json.dumps({"sha": "def"}), replace=True)
        (rec,) = self._records()
        self.assertEqual(json.loads(rec.value), {"sha": "def"})
