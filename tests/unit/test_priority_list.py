import unittest

from lightcycle.adapters.tui.design_system import HUMAN_STEP_GLYPH, STATE_GLYPHS
from lightcycle.adapters.tui.hub import COST_NOT_RECORDED
from lightcycle.adapters.tui.priority_list import (
    _active_row,
    _attention_row,
    _project,
    _queued_row,
    build_priority_rows,
    assemble_rows,
)
from lightcycle.adapters.tui.row_grid import STEP_PHRASE_BUDGET, truncate_field
from lightcycle.application.flow.engine_steps import AUDIT_STEP, FINDINGS_STEP
from tests.support.fake_fs import flow_from_metas
from tests.support.fake_store import FakeStore
from tests.support.step_factory import create_owned_step


class TestProject(unittest.TestCase):
    def test_resolves_via_its_items_repo(self):
        store = FakeStore()
        item = store.create_item("story", "a description")
        store.add_artifact(item, "repo", "lightcycle")
        step = store.create_step("build", step="build", role="agent", parent=item)
        node = store.get_node(step)
        self.assertEqual(_project(store, node), "lightcycle")

    def test_blank_when_its_item_has_no_repo(self):
        store = FakeStore()
        item = store.create_item("story", "a description")
        step = store.create_step("build", step="build", role="agent", parent=item)
        node = store.get_node(step)
        self.assertEqual(_project(store, node), "")

    def test_resolves_from_the_item_when_given_an_item(self):
        store = FakeStore()
        item = store.create_item("story", "a description")
        store.add_artifact(item, "repo", "lightcycle")
        self.assertEqual(_project(store, store.get_item(item)), "lightcycle")

    def test_derives_the_short_label_from_a_slash_qualified_repo_artifact(self):
        store = FakeStore()
        item = store.create_item("story", "a description")
        store.add_artifact(item, "repo", "kenmclennan/lightcycle")
        step = store.create_step("build", step="build", role="agent", parent=item)
        node = store.get_node(step)
        self.assertEqual(_project(store, node), "lightcycle")


class TestQueuedRowDependencyTieBreak(unittest.TestCase):
    def test_shows_lexicographically_lowest_blocker(self):
        store = FakeStore()
        blocker_a = create_owned_step(store, "blocker a", step="build", role="agent")
        blocker_b = create_owned_step(store, "blocker b", step="build", role="agent")
        blocked = create_owned_step(store, 
            "blocked", step="build", role="agent", deps=[blocker_a, blocker_b]
        )
        node = store.get_node(blocked)
        expected = sorted([blocker_a, blocker_b])[0]
        other = blocker_b if expected == blocker_a else blocker_a

        row = _queued_row(store, node, _FLOW)

        self.assertIn(expected, row.step)
        self.assertNotIn(other, row.step)


class TestQueuedRowHumanGlyph(unittest.TestCase):
    def test_a_dependency_blocked_human_step_shows_the_human_square(self):
        store = FakeStore()
        blocker = create_owned_step(store, "blocker", step="build", role="agent")
        blocked = create_owned_step(store, 
            "blocked", step="await-merge", role="human", deps=[blocker]
        )
        node = store.get_node(blocked)

        row = _queued_row(store, node, _FLOW)

        self.assertEqual(row.icon, HUMAN_STEP_GLYPH.glyph)

    def test_a_dependency_blocked_agent_step_still_shows_the_plain_queued_glyph(self):
        store = FakeStore()
        blocker = create_owned_step(store, "blocker", step="build", role="agent")
        blocked = create_owned_step(store, 
            "blocked", step="build", role="agent", deps=[blocker]
        )
        node = store.get_node(blocked)

        row = _queued_row(store, node, _FLOW)

        self.assertEqual(row.icon, STATE_GLYPHS["queued"].glyph)


_FLOW = flow_from_metas(
    {
        "coder": {"model": "sonnet", "step": "build", "routes": {"done": "review"}},
        "ready-merge": {"step": "ready-merge", "routes": {"merged": "cleanup", "changes": "build"}},
    }
)


class TestAttentionRow(unittest.TestCase):
    def test_a_human_owned_step_is_a_gate(self):
        store = FakeStore()
        step = create_owned_step(store, "await merge", step="ready-merge", role="human")
        node = store.get_node(step)

        row = _attention_row(store, node, _FLOW)

        self.assertEqual(row.icon, "●")
        self.assertEqual(row.icon_colour, "amber")
        self.assertEqual(row.step, node.step)

    def test_a_step_unknown_to_the_flow_is_a_gate(self):
        store = FakeStore()
        step = create_owned_step(store, "triage", step="triage", role="human")
        node = store.get_node(step)

        row = _attention_row(store, node, _FLOW)

        self.assertEqual(row.icon, "●")
        self.assertEqual(row.icon_colour, "amber")
        self.assertEqual(row.step, node.step)

    def test_an_agent_owned_step_is_an_escalation(self):
        store = FakeStore()
        step = create_owned_step(store, "stuck build", step="build", role="human")
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
        step = create_owned_step(store, "await merge", step="ready-merge", role="human")
        node = store.get_node(step)

        row = _attention_row(store, node, _FLOW_WITH_DISPLAY)

        self.assertEqual(row.step, "Review the PR")

    def test_an_escalation_carries_its_declared_display_phrase_in_the_stuck_prefix(self):
        store = FakeStore()
        step = create_owned_step(store, "stuck build", step="build", role="human")
        node = store.get_node(step)

        row = _attention_row(store, node, _FLOW_WITH_DISPLAY)

        self.assertEqual(row.step, "stuck · Coding")


class TestActiveRowDisplayPhrase(unittest.TestCase):
    def test_shows_its_declared_display_phrase(self):
        store = FakeStore()
        step = create_owned_step(store, "building", step="build", role="agent")
        node = store.get_node(step)

        row = _active_row(store, node, _FLOW_WITH_DISPLAY)

        self.assertEqual(row.step, "Coding")


class TestQueuedRowDisplayPhrase(unittest.TestCase):
    def test_shows_its_declared_display_phrase(self):
        store = FakeStore()
        step = create_owned_step(store, "queued build", step="build", role="agent")
        node = store.get_node(step)

        row = _queued_row(store, node, _FLOW_WITH_DISPLAY)

        self.assertEqual(row.step, "Coding")

    def test_a_blocked_row_shows_the_blockers_id_not_the_declared_phrase(self):
        store = FakeStore()
        blocker = create_owned_step(store, "blocker", step="ready-merge", role="human")
        blocked = create_owned_step(store, "blocked", step="build", role="agent", deps=[blocker])
        node = store.get_node(blocked)

        row = _queued_row(store, node, _FLOW_WITH_DISPLAY)

        self.assertEqual(row.step, "blocked · %s" % blocker)
        self.assertNotIn("Coding", row.step)


class TestEngineStepDisplayPhrase(unittest.TestCase):
    def test_a_findings_gate_shows_the_engine_phrase(self):
        store = FakeStore()
        step = create_owned_step(store, "review findings", step=FINDINGS_STEP, role="human")
        node = store.get_node(step)

        row = _attention_row(store, node, _FLOW)

        self.assertEqual(row.step, truncate_field("Review the findings", STEP_PHRASE_BUDGET))

    def test_an_active_audit_shows_the_engine_phrase(self):
        store = FakeStore()
        step = create_owned_step(store, "auditing", step=AUDIT_STEP, role="agent")
        node = store.get_node(step)

        row = _active_row(store, node, _FLOW)

        self.assertEqual(row.step, truncate_field("Auditing recent work", STEP_PHRASE_BUDGET))

    def test_a_queued_audit_shows_the_engine_phrase(self):
        store = FakeStore()
        step = create_owned_step(store, "queued audit", step=AUDIT_STEP, role="agent")
        node = store.get_node(step)

        row = _queued_row(store, node, _FLOW)

        self.assertEqual(row.step, truncate_field("Auditing recent work", STEP_PHRASE_BUDGET))


class FixedFlowService:
    def __init__(self, flow):
        self._flow = flow

    def flow_for(self, node):
        return self._flow


class TestBuildPriorityRowsAttentionSort(unittest.TestCase):
    def test_escalation_sorts_before_gate_when_gate_listed_first(self):
        store = FakeStore()
        gate = create_owned_step(store, "await merge", step="ready-merge", role="human")
        escalation = create_owned_step(store, "stuck build", step="build", role="human")
        lanes = {
            "inbox": [store.get_node(gate), store.get_node(escalation)],
            "queue": [],
            "active": [],
        }

        attention, _, _ = build_priority_rows(store, lanes, FixedFlowService(_FLOW))

        self.assertEqual(
            [row.id for row in attention],
            [store.get_step(escalation).item, store.get_step(gate).item],
        )

    def test_escalation_sorts_before_gate_when_escalation_listed_first(self):
        store = FakeStore()
        escalation = create_owned_step(store, "stuck build", step="build", role="human")
        gate = create_owned_step(store, "await merge", step="ready-merge", role="human")
        lanes = {
            "inbox": [store.get_node(escalation), store.get_node(gate)],
            "queue": [],
            "active": [],
        }

        attention, _, _ = build_priority_rows(store, lanes, FixedFlowService(_FLOW))

        self.assertEqual(
            [row.id for row in attention],
            [store.get_step(escalation).item, store.get_step(gate).item],
        )


class TestBuildPriorityRowsStepId(unittest.TestCase):
    def test_attention_row_step_id_is_the_step_not_the_owning_item(self):
        store = FakeStore()
        item = store.create_item("story", "a description")
        step = store.create_step("await merge", step="ready-merge", role="human", parent=item)
        lanes = {"inbox": [store.get_node(step)], "queue": [], "active": []}

        attention, _, _ = build_priority_rows(store, lanes, FixedFlowService(_FLOW))

        self.assertEqual(attention[0].id, item)
        self.assertEqual(attention[0].step_id, step)

    def test_active_row_step_id_is_the_step_not_the_owning_item(self):
        store = FakeStore()
        item = store.create_item("story", "a description")
        step = store.create_step("building", step="build", role="agent", parent=item)
        lanes = {"inbox": [], "queue": [], "active": [store.get_node(step)]}

        _, active, _ = build_priority_rows(store, lanes, FixedFlowService(_FLOW))

        self.assertEqual(active[0].id, item)
        self.assertEqual(active[0].step_id, step)

    def test_queued_row_step_id_is_the_step_not_the_owning_item(self):
        store = FakeStore()
        item = store.create_item("story", "a description")
        step = store.create_step("queued build", step="build", role="agent", parent=item)
        lanes = {"inbox": [], "queue": [store.get_node(step)], "active": []}

        _, _, queued = build_priority_rows(store, lanes, FixedFlowService(_FLOW))

        self.assertEqual(queued[0].id, item)
        self.assertEqual(queued[0].step_id, step)

    def test_queued_dependency_held_row_step_id_is_the_step_not_the_owning_item(self):
        store = FakeStore()
        item = store.create_item("story", "a description")
        blocker = create_owned_step(store, "blocker", step="ready-merge", role="human")
        step = store.create_step(
            "blocked build", step="build", role="agent", parent=item, deps=[blocker]
        )
        lanes = {"inbox": [], "queue": [store.get_node(step)], "active": []}

        _, _, queued = build_priority_rows(store, lanes, FixedFlowService(_FLOW))

        self.assertEqual(queued[0].id, item)
        self.assertEqual(queued[0].step_id, step)


class TestBuildPriorityRowsCost(unittest.TestCase):
    def test_active_row_shows_the_items_rolled_up_cost_across_all_its_steps(self):
        store = FakeStore()
        item = store.create_item("story", "a description")
        done = store.create_step("spec", step="spec-writer", role="agent", parent=item)
        store.record_usage(done, 100, 10, 0, 0, 2.50, "list", None)
        store.complete_node(done, "done")
        step = store.create_step("building", step="build", role="agent", parent=item)
        store.record_usage(step, 100, 10, 0, 0, 1.25, "list", None)
        lanes = {"inbox": [], "queue": [], "active": [store.get_node(step)]}

        _, active, _ = build_priority_rows(store, lanes, FixedFlowService(_FLOW))

        self.assertEqual(active[0].cost, "$3.75")

    def test_a_row_with_turns_but_no_recorded_cost_shows_the_not_recorded_placeholder(self):
        store = FakeStore()
        item = store.create_item("story", "a description")
        step = store.create_step("building", step="build", role="agent", parent=item)
        store.record_attribution(step, 50, {})
        lanes = {"inbox": [], "queue": [], "active": [store.get_node(step)]}

        _, active, _ = build_priority_rows(store, lanes, FixedFlowService(_FLOW))

        self.assertEqual(active[0].cost, COST_NOT_RECORDED)

    def test_a_row_that_has_never_run_anything_is_blank_not_zero_dollars(self):
        store = FakeStore()
        item = store.create_item("story", "a description")
        step = store.create_step("building", step="build", role="agent", parent=item)
        lanes = {"inbox": [], "queue": [], "active": [store.get_node(step)]}

        _, active, _ = build_priority_rows(store, lanes, FixedFlowService(_FLOW))

        self.assertEqual(active[0].cost, "")


class TestBuildPriorityRowsTime(unittest.TestCase):
    def test_a_row_that_has_never_accrued_active_time_is_blank(self):
        store = FakeStore()
        item = store.create_item("story", "a description")
        step = store.create_step("building", step="build", role="agent", parent=item)
        lanes = {"inbox": [], "queue": [], "active": [store.get_node(step)]}

        _, active, _ = build_priority_rows(store, lanes, FixedFlowService(_FLOW))

        self.assertEqual(active[0].time, "")

    def test_active_row_shows_the_items_summed_active_time_across_all_its_steps(self):
        store = FakeStore()
        item = store.create_item("story", "a description")
        done = store.create_step("spec", step="spec-writer", role="agent", parent=item)
        store.accrue_active_seconds([done], 300)
        store.complete_node(done, "done")
        step = store.create_step("building", step="build", role="agent", parent=item)
        store.accrue_active_seconds([step], 540)
        lanes = {"inbox": [], "queue": [], "active": [store.get_node(step)]}

        _, active, _ = build_priority_rows(store, lanes, FixedFlowService(_FLOW))

        self.assertEqual(active[0].time, "14m")

    def test_an_attention_row_shows_accumulated_time_from_an_earlier_done_agent_step(self):
        store = FakeStore()
        item = store.create_item("story", "a description")
        done = store.create_step("spec", step="spec-writer", role="agent", parent=item)
        store.accrue_active_seconds([done], 540)
        store.complete_node(done, "done")
        gate = store.create_step(
            "await merge", step="ready-merge", role="human", parent=item
        )
        lanes = {"inbox": [store.get_node(gate)], "queue": [], "active": []}

        attention, _, _ = build_priority_rows(store, lanes, FixedFlowService(_FLOW))

        self.assertEqual(attention[0].time, "9m")

    def test_a_queued_row_shows_the_same_rolled_up_total_as_active_or_attention(self):
        store = FakeStore()
        item = store.create_item("story", "a description")
        done = store.create_step("spec", step="spec-writer", role="agent", parent=item)
        store.accrue_active_seconds([done], 540)
        store.complete_node(done, "done")
        step = store.create_step("queued build", step="build", role="agent", parent=item)
        lanes = {"inbox": [], "queue": [store.get_node(step)], "active": []}

        _, _, queued = build_priority_rows(store, lanes, FixedFlowService(_FLOW))

        self.assertEqual(queued[0].time, "9m")


class TestAssembleRows(unittest.TestCase):
    def test_concatenates_all_three_groups_with_no_separator(self):
        self.assertEqual(assemble_rows(["a"], ["b"], ["c"]), ["a", "b", "c"])

    def test_an_empty_middle_group_contributes_nothing(self):
        self.assertEqual(assemble_rows(["a"], [], ["c"]), ["a", "c"])

    def test_a_single_non_empty_group_renders_alone(self):
        self.assertEqual(assemble_rows([], [], ["c"]), ["c"])
