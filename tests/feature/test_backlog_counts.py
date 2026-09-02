import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from lightcycle.application.work.backlog import BacklogInput, BacklogUseCase
from tests.support.fake_store import FakeStore

scenarios("backlog-counts.feature")


@pytest.fixture
def ctx():
    return {"store": FakeStore()}


@given(parsers.re(
    r'the registered project "(?P<identity>[^"]+)" with (?P<count>\d+) '
    r'backlogged items? whose repo is "(?P<repo>[^"]+)"'
))
def _project_with_items(ctx, identity, count, repo):
    ctx["store"].add_project(identity)
    for _ in range(int(count)):
        item = ctx["store"].create_item("item", "a description")
        ctx["store"].add_artifact(item, "repo", repo)


@given(parsers.parse('the registered project "{identity}" with no backlogged items'))
def _project_no_items(ctx, identity):
    ctx["store"].add_project(identity)


@given(parsers.re(r'(?P<count>\d+) backlogged items? with no repo artifact'))
def _unscoped_items(ctx, count):
    for _ in range(int(count)):
        ctx["store"].create_item("unscoped item", "a description")


@given(parsers.re(
    r'(?P<count>\d+) backlogged items? whose repo is "(?P<repo>[^"]+)", '
    r'which matches no registered project'
))
def _unmatched_repo_items(ctx, count, repo):
    for _ in range(int(count)):
        item = ctx["store"].create_item("unmatched item", "a description")
        ctx["store"].add_artifact(item, "repo", repo)


@given("no registered projects")
def _no_projects():
    pass


@given("no backlogged items")
def _no_items():
    pass


@when("the backlog counts are read")
def _read_counts(ctx):
    ctx["counts"] = BacklogUseCase(ctx["store"], None).counts()


@when(parsers.parse('the backlog is read filtered to the reported project value for "{project}"'))
def _read_filtered(ctx, project):
    pc = next(p for p in ctx["counts"].projects if p.project == project)
    ctx["filtered_resp"] = BacklogUseCase(ctx["store"], None).execute(BacklogInput(project=pc.project))


@then(parsers.parse('project "{project}" reports count {count:d}'))
def _project_count(ctx, project, count):
    pc = next(p for p in ctx["counts"].projects if p.project == project)
    assert pc.count == count


@then(parsers.parse("the unscoped count is {count:d}"))
def _unscoped_count(ctx, count):
    assert ctx["counts"].unscoped == count


@then(parsers.parse("the total count is {count:d}"))
def _total_count(ctx, count):
    assert ctx["counts"].total == count


@then("the total count is greater than the sum of the project counts and the unscoped count")
def _total_gt(ctx):
    bucketed = sum(p.count for p in ctx["counts"].projects) + ctx["counts"].unscoped
    assert ctx["counts"].total > bucketed


@then(parsers.parse('the number of rows returned equals the count reported for "{project}"'))
def _rows_equal_count(ctx, project):
    pc = next(p for p in ctx["counts"].projects if p.project == project)
    assert len(ctx["filtered_resp"].rows) == pc.count


@then("the projects list is empty")
def _projects_empty(ctx):
    assert ctx["counts"].projects == []
