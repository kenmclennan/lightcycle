import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from tests.support.restack_world import GATE, RestackWorld

scenarios("restacking-stacked-slices.feature")

NAME = "feat"


@pytest.fixture
def world():
    return RestackWorld()


def _build(world, count=3, plain=(), bases=None, unbased=()):
    world.add_slices(NAME, count=count, plain=plain, bases=bases, unbased=unbased)


def _slice(world, n):
    return world.nodes["%s-s%d" % (NAME, n)]


def _restacks(world):
    return [c for c in world.git.calls if c[0] == "restack"]


def _branches(call):
    return [s.branch for s in call[2]]


def _branch(n):
    return "feat/%s-s%d" % (NAME, n)


@given("a three-slice item")
def _three(world):
    _build(world)


@given("a two-slice item")
def _two(world):
    _build(world, 2)


@given("a two-slice item whose slice 2 was created after slice 1 merged")
def _two_unbased(world):
    _build(world, 2, unbased=(2,))


@given("a three-slice item whose slice 3 coder is running")
def _three_coding(world):
    _build(world, plain=(3,))


@given("a three-slice item with a child item stacked on it")
def _three_child(world):
    _build(world)
    world.add_node("child", parent=NAME, commits=["m1"], stack_base=_slice(world, 3)["tip"])


@given("a three-slice item with a child item stacked on it whose slice 3 coder is running")
def _three_child_coding(world):
    _build(world, plain=(3,))
    world.add_node("child", parent=NAME, commits=["m1"], stack_base=_slice(world, 3)["tip"])


@given("a four-slice item where slice 4 is stacked on slice 1")
def _four(world):
    _build(world, 4, bases={4: 1})


@given("a four-slice item where slice 4 is stacked on slice 1 and slice 2 coder is running")
def _four_coding(world):
    _build(world, 4, bases={4: 1}, plain=(2,))


@given("slice 1 is squash-merged")
def _merged(world):
    world.merge("%s-s1" % NAME)


@given("slice 1's head has moved")
def _moved(world):
    world.set_head("%s-s1" % NAME, "s1-new-head")


@given(parsers.parse('slice {n:d}\'s rebase conflicts in "{path}"'))
def _conflict(world, n, path):
    world.conflicts[_branch(n)] = [path]


@when("slice 3 reaches its gate")
def _gate(world):
    entry = _slice(world, 3)
    world.store.complete_node(entry["step"], "done")
    entry["step"] = world.store.create_step(
        stage=GATE, role="agent", item=entry["item"], slice=3)
    s2 = _slice(world, 2)
    world.set_head("%s-s2" % NAME, world.git.remote_tips[s2["branch"]])


@when("the engine restacks")
def _restack(world):
    if getattr(world, "use_case_under_test", None) is None:
        world.use_case_under_test = world.use_case()
    world.first = world.use_case_under_test.execute()


@then("slice 2's PR base is edited to the default branch before the rebase")
def _base_first(world):
    pr = _slice(world, 2)["pr"]
    assert world.github.base_edits == [(pr, "main")]
    assert (pr, "main") in world.events[0][2]


@then("one restack moves slices 2 and 3 in stack order")
def _s23(world):
    calls = _restacks(world)
    assert len(calls) == 1
    assert _branches(calls[0]) == [_branch(2), _branch(3)]
    by_branch = {s.branch: s for s in calls[0][2]}
    assert by_branch[_branch(2)].onto == "origin/main"
    assert by_branch[_branch(3)].onto == _branch(2)


@then("only slice 2 is marked retargeted")
def _marker(world):
    labels = {
        a.label for a in world.store.item_artifacts(_slice(world, 2)["item"])
        if a.type == "stack-retargeted"
    }
    assert labels == {_slice(world, 2)["run"]}


@then("slice 2 is told its head moved")
def _told(world):
    assert "restacked %s" % _branch(2) in (
        world.store.get_node(_slice(world, 2)["step"]).notes or "")
    assert world.nodes["%s-s2" % NAME]["pr"] in world.stale


@then("a second pass does not restack again")
def _no_retry(world):
    before = len(_restacks(world))
    world.sync_heads()
    world.use_case_under_test.execute()
    assert len(_restacks(world)) == before


@then("one restack moves slice 2 only")
def _s2_only(world):
    calls = _restacks(world)
    assert len(calls) == 1
    assert _branches(calls[0]) == [_branch(2)]


@then("one restack moves slice 4 only")
def _s4_only(world):
    calls = _restacks(world)
    assert len(calls) == 1
    assert _branches(calls[0]) == [_branch(4)]


@then("one restack moves slices 2, 3 and 4 in stack order")
def _s234(world):
    calls = _restacks(world)
    assert len(calls) == 1
    assert _branches(calls[0]) == [_branch(2), _branch(3), _branch(4)]


@then("one restack moves slices 2 and 3 and the child item in order")
def _with_child(world):
    calls = _restacks(world)
    assert len(calls) == 1
    assert _branches(calls[0]) == [_branch(2), _branch(3), "feat/child"]


@then("the second restack moves slice 3 only")
def _second(world):
    calls = _restacks(world)
    assert len(calls) == 2
    assert _branches(calls[1]) == [_branch(3)]
    assert calls[1][2][0].onto == "origin/" + _branch(2)


@then(parsers.parse("slice {n:d}'s step carries a deferral note"))
def _deferral(world, n):
    notes = world.store.get_node(_slice(world, n)["step"]).notes or ""
    assert "restack of %s deferred" % _branch(n) in notes


@then(parsers.parse("slice {n:d}'s branch is unmoved"))
def _unmoved(world, n):
    entry = _slice(world, n)
    assert world.git.remote_tips[entry["branch"]] == entry["tip"]


@then(parsers.parse('slice {n:d}\'s step is completed with the gave-up outcome naming "{path}"'))
def _escalated(world, n, path):
    node = world.store.get_node(_slice(world, n)["step"])
    assert node.state == "done"
    assert node.outcome == "gave-up"
    assert path in str(node)


@then("nothing is restacked")
def _nothing(world):
    assert not _restacks(world)


@then("no base edit is made")
def _no_edit(world):
    assert world.github.base_edits == []
