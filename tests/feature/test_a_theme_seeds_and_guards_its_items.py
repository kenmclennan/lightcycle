import os

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

import lightcycle.cli as cli
from tests.support.harness import Harness

scenarios("a-theme-seeds-and-guards-its-items.feature")


@pytest.fixture
def ctx():
    return {}


@pytest.fixture(autouse=True)
def _isolate():
    saved = dict(os.environ)
    orig = cli.container()
    yield
    os.environ.clear()
    os.environ.update(saved)
    cli.set_container(orig)


def _new_theme(ctx, repo=None, title="objective"):
    args = ["new", "theme", title]
    if repo:
        args += ["--repo", repo]
    rc, out, err = ctx["h"].run(*args)
    assert rc == 0, err
    return out.strip()


def _new_item(ctx, parent, repo=None, title="some item"):
    args = ["new", "item", title, "--parent", parent]
    if repo:
        args += ["--repo", repo]
    rc, out, err = ctx["h"].run(*args)
    assert rc == 0, err
    return out.strip()


def _item_repo(ctx, item):
    artifacts = ctx["h"].store.item_artifacts(item)
    return next((a.value for a in artifacts if a.type == "repo"), None)


@given(parsers.parse('a theme with repo "{repo}"'))
def _theme_with_repo(ctx, repo):
    ctx["h"] = Harness([])
    ctx["theme"] = _new_theme(ctx, repo=repo)


@given("a theme with no repo")
def _theme_with_no_repo(ctx):
    ctx["h"] = Harness([])
    ctx["theme"] = _new_theme(ctx)


@given("a theme with one open item beneath it")
def _theme_with_open_item(ctx):
    ctx["h"] = Harness([])
    ctx["theme"] = _new_theme(ctx)
    ctx["item"] = _new_item(ctx, ctx["theme"])


@when("I create an item under that theme, with no repo of its own")
def _create_item_no_repo(ctx):
    ctx["item"] = _new_item(ctx, ctx["theme"])


@when(parsers.parse('I create an item under that theme, with its own repo "{repo}"'))
def _create_item_with_repo(ctx, repo):
    ctx["item"] = _new_item(ctx, ctx["theme"], repo=repo)


@when(parsers.parse('I close the theme with outcome "{outcome}"'))
def _close_theme(ctx, outcome):
    ctx["rc"], ctx["out"], ctx["err"] = ctx["h"].run("done", ctx["theme"], outcome)


@then(parsers.parse('the item\'s repo is "{repo}"'))
def _item_repo_is(ctx, repo):
    assert _item_repo(ctx, ctx["item"]) == repo


@then("the item has no repo artifact at all")
def _item_has_no_repo(ctx):
    assert _item_repo(ctx, ctx["item"]) is None


@then("the command is rejected")
def _rejected(ctx):
    assert ctx["rc"] != 0


@then("the refusal names the open item")
def _refusal_names_item(ctx):
    assert ctx["item"] in ctx["err"]


@then("the theme is still ready")
def _theme_still_ready(ctx):
    assert ctx["h"].store.get_node(ctx["theme"]).state == "ready"


@then("the item is still backlogged")
def _item_still_backlogged(ctx):
    assert ctx["h"].store.get_node(ctx["item"]).state == "backlogged"
