import unittest

from lightcycle.adapters.tui.priority_list import (
    _active_row,
    _attention_row,
    _project,
    _queued_row,
    build_priority_rows,
    assemble_rows,
)
from tests.support.fake_fs import flow_from_metas
from tests.support.fake_store import FakeStore


class TestProject(unittest.TestCase):
    def test_resolves_via_parent_items_repo_artifact(self):
        store = FakeStore()
        item = store.create_item("story")
        store.add_artifact(item, "repo", "lightcycle")
        step = store.create_step("build", step="build", role="coder", parent=item)
        node = store.get_node(step)
        self.assertEqual(_project(store, node), "lightcycle")

    def test_blank_when_parent_item_has_no_repo_artifact(self):
        store = FakeStore()
        item = store.create_item("story")
        step = store.create_step("build", step="build", role="coder", parent=item)
        node = store.get_node(step)
        self.assertEqual(_project(store, node), "")

    def test_resolves_via_own_id_when_no_parent(self):
        store = FakeStore()
        step = store.create_step("build", step="build", role="coder")
        store.add_artifact(step, "repo", "lightcycle")
        node = store.get_node(step)
        self.assertEqual(_project(store, node), "lightcycle")

    def test_derives_the_short_label_from_a_slash_qualified_repo_artifact(self):
        store = FakeStore()
        item = store.create_item("story")
        store.add_artifact(item, "repo", "kenmclennan/lightcycle")
        step = store.create_step("build", step="build", role="coder", parent=item)
        node = store.get_node(step)
        self.assertEqual(_project(store, node), "lightcycle")


class TestQueuedRowDependencyTieBreak(unittest.TestCase):
    def test_shows_lexicographically_lowest_blocker(self):
        store = FakeStore()
        blocker_a = store.create_step("blocker a", step="build", role="coder")
        blocker_b = store.create_step("blocker b", step="build", role="coder")
        blocked = store.create_step(
            "blocked", step="build", role="coder", deps=[blocker_a, blocker_b]
        )
        node = store.get_node(blocked)
        expected = sorted([blocker_a, blocker_b])[0]
        other = blocker_b if expected == blocker_a else blocker_a

        row = _queued_row(store, node, _FLOW)

        self.assertIn(expected, row.step)
        self.assertNotIn(other, row.step)


_FLOW = flow_from_metas(
    {
        "coder": {"model": "sonnet", "step": "build", "routes": {"done": "review"}},
        "ready-merge": {"step": "ready-merge", "routes": {"merged": "cleanup", "changes": "build"}},
    }
)


class TestAttentionRow(unittest.TestCase):
    def test_a_human_owned_step_is_a_gate(self):
        store = FakeStore()
        step = store.create_step("await merge", step="ready-merge", role="human")
        node = store.get_node(step)

        row = _attention_row(store, node, _FLOW)

        self.assertEqual(row.icon, "●")
        self.assertEqual(row.icon_colour, "amber")
        self.assertEqual(row.step, node.step)

    def test_a_step_unknown_to_the_flow_is_a_gate(self):
        store = FakeStore()
        step = store.create_step("triage", step="triage", role="human")
        node = store.get_node(step)

        row = _attention_row(store, node, _FLOW)

        self.assertEqual(row.icon, "●")
        self.assertEqual(row.icon_colour, "amber")
        self.assertEqual(row.step, node.step)

    def test_an_agent_owned_step_is_an_escalation(self):
        store = FakeStore()
        step = store.create_step("stuck build", step="build", role="human")
        node = store.get_node(step)

        row = _attention_row(store, node, _FLOW)

        self.assertEqual(row.icon, "▲")
        self.assertEqual(row.icon_colour, "red")
        self.assertEqual(row.step, "stuck · %s" % node.step)


_FLOW_WITH_DISPLAY = flow_from_metas(
    {
        "coder": {
            "model": "sonnet", "step": "build", "display": "Coding",
            "routes": {"done": "review"},
        },
        "ready-merge": {
            "step": "ready-merge", "display": "Review the PR",
            "routes": {"merged": "cleanup", "changes": "build"},
        },
    }
)


class TestAttentionRowDisplayPhrase(unittest.TestCase):
    def test_a_gate_shows_its_declared_display_phrase(self):
        store = FakeStore()
        step = store.create_step("await merge", step="ready-merge", role="human")
        node = store.get_node(step)

        row = _attention_row(store, node, _FLOW_WITH_DISPLAY)

        self.assertEqual(row.step, "Review the PR")

    def test_an_escalation_carries_its_declared_display_phrase_in_the_stuck_prefix(self):
        store = FakeStore()
        step = store.create_step("stuck build", step="build", role="human")
        node = store.get_node(step)

        row = _attention_row(store, node, _FLOW_WITH_DISPLAY)

        self.assertEqual(row.step, "stuck · Coding")


class TestActiveRowDisplayPhrase(unittest.TestCase):
    def test_shows_its_declared_display_phrase(self):
        store = FakeStore()
        step = store.create_step("building", step="build", role="coder")
        node = store.get_node(step)

        row = _active_row(store, node, "now", _FLOW_WITH_DISPLAY)

        self.assertEqual(row.step, "Coding")


class TestQueuedRowDisplayPhrase(unittest.TestCase):
    def test_shows_its_declared_display_phrase(self):
        store = FakeStore()
        step = store.create_step("queued build", step="build", role="coder")
        node = store.get_node(step)

        row = _queued_row(store, node, _FLOW_WITH_DISPLAY)

        self.assertEqual(row.step, "Coding")

    def test_a_blocked_row_shows_the_blockers_id_not_the_declared_phrase(self):
        store = FakeStore()
        blocker = store.create_step("blocker", step="ready-merge", role="human")
        blocked = store.create_step("blocked", step="build", role="coder", deps=[blocker])
        node = store.get_node(blocked)

        row = _queued_row(store, node, _FLOW_WITH_DISPLAY)

        self.assertEqual(row.step, "blocked · %s" % blocker)
        self.assertNotIn("Coding", row.step)


class FixedFlowService:
    def __init__(self, flow):
        self._flow = flow

    def flow_for(self, node):
        return self._flow


class TestBuildPriorityRowsAttentionSort(unittest.TestCase):
    def test_escalation_sorts_before_gate_when_gate_listed_first(self):
        store = FakeStore()
        gate = store.create_step("await merge", step="ready-merge", role="human")
        escalation = store.create_step("stuck build", step="build", role="human")
        lanes = {
            "inbox": [store.get_node(gate), store.get_node(escalation)],
            "queue": [],
            "active": [],
        }

        attention, _, _ = build_priority_rows(store, lanes, "now", FixedFlowService(_FLOW))

        self.assertEqual([row.id for row in attention], [escalation, gate])

    def test_escalation_sorts_before_gate_when_escalation_listed_first(self):
        store = FakeStore()
        escalation = store.create_step("stuck build", step="build", role="human")
        gate = store.create_step("await merge", step="ready-merge", role="human")
        lanes = {
            "inbox": [store.get_node(escalation), store.get_node(gate)],
            "queue": [],
            "active": [],
        }

        attention, _, _ = build_priority_rows(store, lanes, "now", FixedFlowService(_FLOW))

        self.assertEqual([row.id for row in attention], [escalation, gate])


class TestAssembleRows(unittest.TestCase):
    def test_concatenates_all_three_groups_with_no_separator(self):
        self.assertEqual(assemble_rows(["a"], ["b"], ["c"]), ["a", "b", "c"])

    def test_an_empty_middle_group_contributes_nothing(self):
        self.assertEqual(assemble_rows(["a"], [], ["c"]), ["a", "c"])

    def test_a_single_non_empty_group_renders_alone(self):
        self.assertEqual(assemble_rows([], [], ["c"]), ["c"])
