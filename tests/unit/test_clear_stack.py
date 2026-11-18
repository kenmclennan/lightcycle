import json
import unittest

from lightcycle.application.errors import UseCaseError
from lightcycle.application.work.link_artifact import LinkArtifactInput, LinkArtifactUseCase
from lightcycle.cli_commands import COMMANDS, build_parser
from lightcycle.ports.github import StackLayer
from tests.support.fake_github import FakeGitHub
from tests.support.fake_store import FakeStore
from tests.unit.test_cmd_source_links import _Container, call

_STACK = "https://github.com/acme/widget/stack/3"
_LAYERS = (
    StackLayer(4, "https://github.com/acme/widget/pull/4", "a", "main", "s1", "open"),
    StackLayer(5, "https://github.com/acme/widget/pull/5", "b", "main", "s2", "open"),
)


def _clear(store, github, item, atype="stack"):
    return LinkArtifactUseCase(store, github, flow=None).execute(
        LinkArtifactInput(item=item, atype=atype, value="", clear=True)
    )


def _stacked():
    store = FakeStore()
    item = store.create_item("st", "a description")
    rid = store.open_run(item, store.open_pass(item), "code")
    github = FakeGitHub()
    github.script_stack(_STACK, _LAYERS)
    LinkArtifactUseCase(store, github, flow=None).execute(
        LinkArtifactInput(item=item, atype="stack", value=_STACK)
    )
    return store, github, item, rid


class TestClearStack(unittest.TestCase):
    def test_clear_resets_stack_and_stack_seen(self):
        store, github, item, rid = _stacked()
        self.assertEqual([e["head_ref"] for e in json.loads(store.get_run(rid).stack_seen)], ["a", "b"])
        self.assertTrue(_clear(store, github, item))
        self.assertIsNone(store.get_run(rid).stack)
        self.assertIsNone(store.get_run(rid).stack_seen)

    def test_clear_leaves_pr_and_branch_alone(self):
        store, github, item, rid = _stacked()
        store.set_pr(rid, "https://github.com/acme/widget/pull/5")
        store.set_branch(rid, "feat/x")
        _clear(store, github, item)
        self.assertEqual(store.get_run(rid).pr, "https://github.com/acme/widget/pull/5")
        self.assertEqual(store.get_run(rid).branch, "feat/x")

    def test_clearing_an_absent_stack_is_a_noop(self):
        store = FakeStore()
        item = store.create_item("st", "a description")
        rid = store.open_run(item, store.open_pass(item), "code")
        github = FakeGitHub()
        before = store.get_run(rid).as_dict()
        self.assertFalse(_clear(store, github, item))
        self.assertEqual(store.get_run(rid).as_dict(), before)
        self.assertEqual(github.calls, [])

    def test_a_clear_then_a_set_records_a_fresh_baseline(self):
        store, github, item, rid = _stacked()
        _clear(store, github, item)
        LinkArtifactUseCase(store, github, flow=None).execute(
            LinkArtifactInput(item=item, atype="stack", value=_STACK)
        )
        self.assertEqual(store.get_run(rid).stack, _STACK)
        self.assertEqual([e["head_ref"] for e in json.loads(store.get_run(rid).stack_seen)], ["a", "b"])

    def test_clear_refusals(self):
        store, github, item, rid = _stacked()
        store.add_artifact(item, "design", "d", None)
        with self.assertRaisesRegex(UseCaseError, "only to 'stack'"):
            _clear(store, github, item, atype="design")
        self.assertEqual([a.type for a in store.item_artifacts(item)], ["design"])
        step = store.create_step(stage="code-open-pr", item=item)
        with self.assertRaisesRegex(UseCaseError, "is a step"):
            _clear(store, github, step)
        bare = store.create_item("bare", "a description")
        with self.assertRaisesRegex(UseCaseError, "no open phase run"):
            _clear(store, github, bare)
        with self.assertRaisesRegex(UseCaseError, "empty value"):
            LinkArtifactUseCase(store, github, flow=None).execute(
                LinkArtifactInput(item=item, atype="stack", value="")
            )
        self.assertEqual(store.get_run(rid).stack, _STACK)

    def test_attach_parser_clear_is_exclusive(self):
        parser = build_parser(COMMANDS["attach"])
        self.assertTrue(parser.parse_args(["LC-1", "stack", "--clear"]).clear)
        for argv in (
            ["LC-1", "stack", "x", "--clear"],
            ["LC-1", "stack", "--clear", "--file", "f"],
        ):
            with self.assertRaises(SystemExit):
                parser.parse_args(argv)


class TestAttachClearCommand(unittest.TestCase):
    def setUp(self):
        from lightcycle import cli

        self.cli = cli
        self.store, _github, self.item, self.rid = _stacked()
        cli.set_container(_Container(self.store))

    def test_clear_refuses_reflection_and_feedback_types(self):
        for atype in ("reflection", "feedback"):
            rc, _out, err = call(self.cli.cmd_attach, self.item, atype, "--clear")
            self.assertEqual(rc, 1, atype)
            self.assertIn("only to 'stack'", err)
        self.assertEqual(self.store.get_run(self.rid).stack, _STACK)

    def test_clearing_an_absent_stack_prints_a_noop_line(self):
        bare = self.store.create_item("bare", "d")
        self.store.open_run(bare, self.store.open_pass(bare), "code")
        rc, out, err = call(self.cli.cmd_attach, bare, "stack", "--clear")
        self.assertEqual(rc, 0, err)
        self.assertIn("no-op: '%s' has no stack to clear" % bare, out)

    def test_clearing_a_present_stack_prints_nothing(self):
        rc, out, err = call(self.cli.cmd_attach, self.item, "stack", "--clear")
        self.assertEqual(rc, 0, err)
        self.assertEqual(out, "")
        self.assertIsNone(self.store.get_run(self.rid).stack)
