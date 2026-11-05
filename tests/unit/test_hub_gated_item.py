from lightcycle.adapters.tui.design_system import DEPENDENCY_BLOCKED_EXTRA_GLYPH
from lightcycle.adapters.tui.hub import hierarchy_row_cells
from lightcycle.domain.work import HierarchyRow
from lightcycle.adapters.tui.hub_render import _hierarchy_default_row_id, build_header
from lightcycle.application.services.flow import FlowService
from lightcycle.application.work.activate_item import ActivateItemInput, ActivateItemUseCase
from tests.support.fake_fs import FakeFs, graph_text_from_metas
from tests.support.fake_store import FakeStore
from tests.support.step_factory import create_owned_step

_NOW = "2026-01-01T00:00:00"


def _flow(store):
    metas = {"coder": {"model": "sonnet", "step": "build", "routes": {"done": "review"}}}
    workflow = graph_text_from_metas(metas, entry="build")
    return FlowService(FakeFs(metas, workflow=workflow), store)


def _gated_item(store, flow):
    blocker = create_owned_step(store, "blocker", role="agent")
    item = store.create_item("add refunds", "a description")
    resp = ActivateItemUseCase(store, flow, None, None).execute(
        ActivateItemInput(item=item, workflow="standard", deps=[blocker])
    )
    return item, resp.step, blocker


def test_default_row_of_an_item_gated_through_its_entry_step_is_the_step():
    store = FakeStore()
    item, step, _ = _gated_item(store, _flow(store))
    assert _hierarchy_default_row_id(store, store.get_node(item)) == step


def test_default_row_of_an_item_with_its_own_dependency_is_the_item():
    store = FakeStore()
    flow = _flow(store)
    item, step, blocker = _gated_item(store, flow)
    store.dep_remove(step, blocker)
    other = create_owned_step(store, "other", role="agent")
    store.dep_add(item, other)
    assert _hierarchy_default_row_id(store, store.get_node(item)) == item


def test_header_of_an_item_gated_through_its_entry_step_matches_the_step_header():
    store = FakeStore()
    flow = _flow(store)
    item, step, blocker = _gated_item(store, flow)
    header = build_header(store, store.get_node(item), 0, flow, False, True)
    assert header.dependency_blocked
    assert header.escalation_target == blocker
    assert header.id == item


def test_header_of_an_item_with_its_own_dependency_takes_the_item_branch():
    store = FakeStore()
    flow = _flow(store)
    item, step, blocker = _gated_item(store, flow)
    store.dep_remove(step, blocker)
    other = create_owned_step(store, "other", role="agent")
    store.dep_add(item, other)
    header = build_header(store, store.get_node(item), 0, flow, False, True)
    assert header.escalation_target == other


def test_hierarchy_row_of_an_item_gated_through_its_entry_step_carries_the_dependency_glyph():
    store = FakeStore()
    flow = _flow(store)
    item, _, _ = _gated_item(store, flow)
    icon_cell, *_ = hierarchy_row_cells(
        HierarchyRow(store.get_node(item), 0), flow_service=flow, store=store, now=_NOW,
    )
    assert icon_cell.plain.endswith(DEPENDENCY_BLOCKED_EXTRA_GLYPH.glyph)
