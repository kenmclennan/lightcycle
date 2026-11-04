import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from tests.support.restack_world import RestackWorld

scenarios("restacking-stacked-pull-requests.feature")


@pytest.fixture
def world():
    return RestackWorld()


def _stack(world, children=("child",), grandchild_on=None):
    parent = world.add_node("parent", commits=["m1", "p1"])
    old_head = "p-old-head"
    world.history[old_head] = ["m1", "p1"]
    for name in children:
        world.add_node(name, parent="parent", commits=["m1", "p1", "c-" + name],
                       stack_base=old_head)
    if grandchild_on:
        world.history["%s-tip" % grandchild_on] = ["m1", "p1", "c-" + grandchild_on]
        world.add_node("grandchild", parent=grandchild_on,
                       commits=["m1", "p1", "c-" + grandchild_on, "g1"],
                       stack_base="%s-tip" % grandchild_on)
    world.set_head("parent", "p-new-head")
    return parent


@given("a parent with a child stacked on it")
def _one_child(world):
    _stack(world)


@given("a parent with two children and a grandchild stacked on the first child")
def _fan(world):
    _stack(world, children=("child", "sibling"), grandchild_on="child")


@given("a parent with a child and a grandchild stacked on the child")
def _chain(world):
    _stack(world, grandchild_on="child")


@given("the parent's PR is squash-merged")
def _merged(world):
    world.merge("parent")
    world.set_head("parent", "p-old-head")


@given("the parent's head has moved")
def _moved(world):
    world.set_head("parent", "p-new-head")


@given("the child's PR already targets the default branch")
def _retargeted(world):
    world.github._base_keys[world.nodes["child"]["pr"]] = "acme/widget@main"


@given("the child's recorded base equals the parent's head")
def _equal(world):
    world.set_head("parent", "p-old-head")


@given("the grandchild's branch has moved on origin")
def _lease(world):
    world.remote_tips[world.nodes["grandchild"]["branch"]] = "someone-else"


@given(parsers.parse('the child\'s rebase conflicts in "{path}"'))
def _child_conflict(world, path):
    world.conflicts[world.nodes["child"]["branch"]] = [path]


@given(parsers.parse('the grandchild\'s rebase conflicts in "{path}"'))
def _grandchild_conflict(world, path):
    world.conflicts[world.nodes["grandchild"]["branch"]] = [path]


@given("the child has a running worker step")
def _running(world):
    world.store.create_step(stage="plain-step", role="agent", item=world.item("child"))
    world.store.complete_node(world.step("child"), "done")


@given("the child has an uncommitted worktree")
def _dirty(world):
    world.dirty.add("/repo/.worktrees/%s" % world.item("child"))


@given("the child has no PR yet")
def _no_pr(world):
    world.store.set_pr(world.store.current_run(world.item("child"), None).id, None)


@given("the child has no branch on origin")
def _no_remote(world):
    world.remote_branches.discard(("/repo", world.nodes["child"]["branch"]))


@when("the engine restacks")
def _restack(world):
    world.use_case_under_test = world.use_case()
    world.first = world.use_case_under_test.execute()


@then("the child's PR base is edited to the default branch before the rebase")
def _base_first(world):
    pr = world.nodes["child"]["pr"]
    assert world.github.base_edits == [(pr, "main")]
    assert (pr, "main") in world.events[0][2]


@then("the child is rebased onto the default branch with a lease")
def _rebased(world):
    call = next(c for c in world.git.calls if c[0] == "restack")
    step = call[2][0]
    assert step.branch == world.nodes["child"]["branch"]
    assert step.onto == "origin/main"
    assert step.lease_sha == "child-tip"
    assert step.old_base == "p-old-head"


@then("the child no longer stacks on the parent")
def _unstacked(world):
    assert world.store.get_item(world.item("child")).stacks_on is None


@then("the child's diff against the default branch is its own commits only")
def _own_only(world):
    assert world.own_commits("child") == ["c-child"]


@then("one restack moves three branches in stack order")
def _three(world):
    calls = [c for c in world.git.calls if c[0] == "restack"]
    assert len(calls) == 1
    branches = [s.branch for s in calls[0][2]]
    direct = sorted(["child", "sibling"], key=world.item)
    expected = []
    for name in direct:
        expected.append("feat/" + name)
        if name == "child":
            expected.append("feat/grandchild")
    assert branches == expected
    by_branch = {st.branch: st for st in calls[0][2]}
    assert by_branch["feat/grandchild"].onto == "feat/child"
    assert by_branch["feat/child"].onto == "origin/feat/parent"
    assert branches.index("feat/child") < branches.index("feat/grandchild")


@then("every branch of the stack has a new tip")
def _moved_all(world):
    for name in world.nodes:
        if name == "parent":
            continue
        assert world.git.remote_tips[world.nodes[name]["branch"]].startswith("restacked-")


@then("no branch of the stack has a new tip")
def _moved_none(world):
    for name in world.nodes:
        assert world.git.remote_tips[world.nodes[name]["branch"]] in (
            world.nodes[name]["tip"], "someone-else")


@then("the first child's gate step is told the head moved")
def _told(world):
    notes = world.store.get_node(world.step("child")).notes or ""
    assert "restacked feat/child" in notes
    assert sorted(world.first.restacked) == sorted(
        [world.item("child"), world.item("grandchild"), world.item("sibling")])


@then("the grandchild's step is parked naming its branch")
def _parked(world):
    park = world.store.get_node(world.step("grandchild")).park
    assert "feat/grandchild" in park.reason
    assert "feat/grandchild" in park.needs


@then(parsers.parse('the child\'s step is completed with the gave-up outcome naming "{path}"'))
def _child_escalated(world, path):
    _escalated(world, "child", path)


@then(parsers.parse('the grandchild\'s step is completed with the gave-up outcome naming "{path}"'))
def _grandchild_escalated(world, path):
    _escalated(world, "grandchild", path)


def _escalated(world, name, path):
    node = world.store.get_node(world.step(name))
    assert node.state == "done"
    assert node.outcome == "gave-up"
    assert path in str(node)


@then("a second pass does not restack again")
def _no_retry(world):
    before = len([c for c in world.git.calls if c[0] == "restack"])
    world.use_case_under_test.execute()
    assert len([c for c in world.git.calls if c[0] == "restack"]) == before


@then("the child's step is untouched")
def _untouched(world):
    assert world.store.get_node(world.step("child")).state != "done"


@then("no base edit is made")
def _no_edit(world):
    assert world.github.base_edits == []


@then("nothing is restacked")
def _nothing(world):
    assert not [c for c in world.git.calls if c[0] == "restack"]


@then("one restack moves one branch")
def _one(world):
    calls = [c for c in world.git.calls if c[0] == "restack"]
    assert len(calls) == 1 and len(calls[0][2]) == 1


@then("the child's step carries a deferral note")
def _deferral(world):
    notes = " ".join(
        s.notes or "" for s in world.store.children(world.item("child")) if s.type == "step")
    assert "restack of feat/child deferred" in notes


@then("the child's PR snapshot entry is marked stale")
def _stale(world):
    assert world.nodes["child"]["pr"] in world.stale
