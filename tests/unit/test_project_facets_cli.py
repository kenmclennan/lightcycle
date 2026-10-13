import io
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

import lightcycle.cli as cli_mod
from lightcycle.application.errors import UseCaseError
from lightcycle.application.setup.project_registry import (
    AddProjectInput, AddProjectUseCase, SetProjectFacetsUseCase,
)
from lightcycle.cli import cmd_project
from lightcycle.container import Container
from tests.support.fake_fs import FakeFs
from tests.support.fake_git import FakeGit
from tests.support.fake_store import FakeStore


class _Config:
    def __init__(self, path):
        self._path = path

    def config_path(self):
        return self._path


def _add(store, config, **kw):
    return AddProjectUseCase(store, FakeGit(), config, FakeFs()).execute(AddProjectInput(**kw))


class TestProjectFacets(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        fd, path = tempfile.mkstemp()
        os.close(fd)
        self.addCleanup(os.unlink, path)
        self.config = _Config(path)

    def test_add_with_facets_stores_both_in_order(self):
        r = _add(self.store, self.config, identity="acme/x", facets="kotlin,spring")
        self.assertEqual(self.store.get_project("acme/x").facets, ("kotlin", "spring"))
        self.assertEqual(r.facets, ("kotlin", "spring"))

    def test_add_without_facets_leaves_existing_ones(self):
        _add(self.store, self.config, identity="acme/x", facets="kotlin")
        _add(self.store, self.config, identity="acme/x", shortcode="XX")
        self.assertEqual(self.store.get_project("acme/x").facets, ("kotlin",))

    def test_add_with_facets_on_a_registered_project_replaces_them(self):
        _add(self.store, self.config, identity="acme/x", facets="kotlin")
        r = _add(self.store, self.config, identity="acme/x", facets="spring")
        self.assertTrue(r.changed)
        self.assertEqual(self.store.get_project("acme/x").facets, ("spring",))

    def test_add_with_a_bad_facet_refuses_and_stores_nothing(self):
        with self.assertRaises(UseCaseError) as ctx:
            _add(self.store, self.config, identity="acme/x", facets="Kotlin")
        self.assertIn("'Kotlin'", str(ctx.exception))
        self.assertIsNone(self.store.get_project("acme/x"))

    def test_set_replaces_and_empty_clears(self):
        _add(self.store, self.config, identity="acme/x", facets="kotlin,spring")
        r = SetProjectFacetsUseCase(self.store).execute("acme/x", "hexagonal")
        self.assertTrue(r.changed)
        self.assertEqual(self.store.get_project("acme/x").facets, ("hexagonal",))
        SetProjectFacetsUseCase(self.store).execute("acme/x", "")
        self.assertEqual(self.store.get_project("acme/x").facets, ())

    def test_set_of_an_identical_list_is_unchanged(self):
        _add(self.store, self.config, identity="acme/x", facets="kotlin")
        r = SetProjectFacetsUseCase(self.store).execute("acme/x", "kotlin")
        self.assertFalse(r.changed)

    def test_set_on_an_unregistered_identity_names_the_registered_ones(self):
        _add(self.store, self.config, identity="acme/x")
        with self.assertRaises(UseCaseError) as ctx:
            SetProjectFacetsUseCase(self.store).execute("acme/ghost", "a")
        self.assertEqual(
            str(ctx.exception), "project 'acme/ghost' is not registered - registered: acme/x"
        )

    def test_set_with_nothing_registered_names_the_add_fix(self):
        with self.assertRaises(UseCaseError) as ctx:
            SetProjectFacetsUseCase(self.store).execute("acme/ghost", "a")
        self.assertIn("none registered yet; run `lc project add <owner/name>", str(ctx.exception))

    def test_set_without_facets_refuses(self):
        _add(self.store, self.config, identity="acme/x")
        with self.assertRaises(UseCaseError) as ctx:
            SetProjectFacetsUseCase(self.store).execute("acme/x", None)
        self.assertIn("nothing to set - pass --facets", str(ctx.exception))

    def test_set_with_a_bad_facet_refuses_and_keeps_the_old_ones(self):
        _add(self.store, self.config, identity="acme/x", facets="kotlin")
        with self.assertRaises(UseCaseError):
            SetProjectFacetsUseCase(self.store).execute("acme/x", "a_b")
        self.assertEqual(self.store.get_project("acme/x").facets, ("kotlin",))

    def test_set_works_on_a_bare_identity_such_as_guidance(self):
        self.store.add_project("guidance", local_path="/kb")
        SetProjectFacetsUseCase(self.store).execute("guidance", "okf")
        self.assertEqual(self.store.get_project("guidance").facets, ("okf",))


class TestCmdProjectFacets(unittest.TestCase):
    def setUp(self):
        self._orig = cli_mod._container
        self.addCleanup(lambda: cli_mod.set_container(self._orig))
        self.store = FakeStore()
        cli_mod.set_container(Container(
            config=object(), git=FakeGit(), store=self.store, spawner=object(),
            workers=object(), fs=object(), github=object(), lock=object(), breaker=object(),
        ))

    def _run(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = cmd_project(list(argv)) or 0
        return rc, out.getvalue(), err.getvalue()

    def test_set_prints_the_new_facets_then_cleared_then_unchanged(self):
        self.store.add_project("acme/x", shortcode="X")
        self.assertEqual(self._run("set", "acme/x", "--facets", "a,b")[1], "acme/x -> facets a,b\n")
        self.assertEqual(self._run("set", "acme/x", "--facets", "a,b")[1], "acme/x facets unchanged\n")
        self.assertEqual(self._run("set", "acme/x", "--facets", "")[1], "acme/x -> no facets\n")

    def test_set_refusal_exits_1_on_stderr(self):
        rc, out, err = self._run("set", "acme/ghost", "--facets", "a")
        self.assertEqual(rc, 1)
        self.assertIn("not registered", err)

    def test_list_prints_facets_as_a_fourth_column_empty_when_none(self):
        self.store.add_project("acme/a", shortcode="A", local_path="/p/a", facets=("kotlin", "spring"))
        self.store.add_project("acme/b", shortcode="B", local_path="/p/b")
        rc, out, _ = self._run("list")
        self.assertEqual(out.splitlines(), ["acme/a\tA\t/p/a\tkotlin,spring", "acme/b\tB\t/p/b\t"])
