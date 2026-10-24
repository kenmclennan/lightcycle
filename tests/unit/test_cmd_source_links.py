import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from lightcycle import cli
from lightcycle.domain.work import worker_permitted
from tests.support.fake_store import FakeStore
from tests.unit.test_review_yield import _FLOW, _FlowAdapter, _Rig


def call(fn, *args):
    out, err = io.StringIO(), io.StringIO()
    try:
        with redirect_stdout(out), redirect_stderr(err):
            rc = fn(list(args)) or 0
    except SystemExit as e:
        rc = e.code if isinstance(e.code, int) else 1
    return rc, out.getvalue(), err.getvalue()


class _Config:
    def max_title_length(self):
        return 200

    def context_artifact_types(self):
        return frozenset()

    def spawn_id(self):
        return None


class _Container:
    def __init__(self, store):
        self.store = store
        self.config = _Config()
        self.git = None
        self.fs = None
        self.workflow_source = None
        self.workflow_bundle = None
        self.scaffold = None


class TestSourceLinkFlags(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        cli.set_container(_Container(self.store))
        self.store.add_project("acme/app", shortcode="APP")
        self.source = self.store.create_item("source", "d")

    def _links(self, item, atype):
        return [a.value for a in self.store.item_artifacts(item) if a.type == atype]

    def test_new_item_stores_repeated_caused_by_and_found_by(self):
        other = self.store.create_item("other", "d")
        rc, out, err = call(
            cli.cmd_new, "item", "fix", "--description", "d", "--project", "app", "--caused-by", self.source,
            "--caused-by", other,
            "--found-by", "runtime")
        self.assertEqual(rc, 0, err)
        fix = out.strip()
        self.assertEqual(self._links(fix, "caused-by"), [self.source, other])
        self.assertEqual(self._links(fix, "found-by"), ["runtime"])

    def test_new_item_with_an_unknown_target_creates_nothing(self):
        before = len(self.store.all_items())
        rc, _out, err = call(cli.cmd_new, "item", "fix", "--description", "d", "--project", "app", "--caused-by", "NOPE-9")
        self.assertEqual(rc, 1)
        self.assertIn("NOPE-9", err)
        self.assertEqual(len(self.store.all_items()), before)

    def test_new_step_refuses_both_flags_naming_the_owning_structure(self):
        rc, _out, err = call(
            cli.cmd_new, "step", "t", "--step", "build", "--parent", self.source,
            "--caused-by", self.source)
        self.assertEqual(rc, 2)
        self.assertIn("belong to an item, not a step", err)

    def test_set_replaces_corrects_and_unsets(self):
        fix = self.store.create_item("fix", "d")
        other = self.store.create_item("other", "d")
        self.assertEqual(call(cli.cmd_set, fix, "--caused-by", self.source)[0], 0)
        self.assertEqual(call(cli.cmd_set, fix, "--caused-by", other, "--found-by", "audit")[0], 0)
        self.assertEqual(self._links(fix, "caused-by"), [other])
        self.assertEqual(self._links(fix, "found-by"), ["audit"])
        rc, _out, err = call(cli.cmd_set, fix, "--unset", "caused-by", "--unset", "found-by")
        self.assertEqual(rc, 0, err)
        self.assertEqual(self._links(fix, "caused-by"), [])
        self.assertEqual(self._links(fix, "found-by"), [])

    def test_set_on_a_step_refuses_naming_both_structures(self):
        step = self.store.create_step(stage="build", role="agent", item=self.source)
        rc, _out, err = call(cli.cmd_set, step, "--caused-by", self.source)
        self.assertEqual(rc, 2)
        self.assertIn("--caused-by belongs to an item, not a step", err)

    def test_set_with_a_title_and_a_link_does_both(self):
        fix = self.store.create_item("fix", "d")
        rc, _out, err = call(cli.cmd_set, fix, "--title", "renamed", "--caused-by", self.source)
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.store.get_item(fix).title, "renamed")
        self.assertEqual(self._links(fix, "caused-by"), [self.source])

    def test_attach_refuses_the_link_types(self):
        fix = self.store.create_item("fix", "d")
        rc, _out, err = call(cli.cmd_attach, fix, "caused-by", self.source)
        self.assertEqual(rc, 1)
        self.assertIn("lc set", err)

    def test_workers_are_refused_both_flags(self):
        for flag in ("caused_by", "found_by"):
            self.assertFalse(worker_permitted("set", {"state": "waiting", flag: ["x"]}), flag)
        self.assertTrue(worker_permitted("review-yield", {}))
        self.assertFalse(worker_permitted("new", {}))


class TestReviewYieldCommand(unittest.TestCase):
    def setUp(self):
        rig = _Rig()
        rig.to_gate()
        rig.done("changes", note="n")
        self.store = rig.store
        cli.set_container(_Container(self.store))

    def test_json_output_carries_every_binding_key(self):
        with mock.patch("lightcycle.commands.feedback._flow", return_value=_FlowAdapter(_FLOW)):
            rc, out, err = call(cli.cmd_review_yield, "--json", "--since", "2000-01-01")
        self.assertEqual(rc, 0, err)
        report = json.loads(out)
        self.assertEqual(
            set(report), {"since", "stages", "unattributed_escapes", "undeclared_steps"})
        self.assertEqual(report["since"], "2000-01-01")
        self.assertEqual(report["stages"][0]["escapes"]["count"], 1)

    def test_text_output_prints_one_line_per_stage_and_the_counts(self):
        with mock.patch("lightcycle.commands.feedback._flow", return_value=_FlowAdapter(_FLOW)):
            rc, out, err = call(cli.cmd_review_yield)
        self.assertEqual(rc, 0, err)
        self.assertIn("review-code: 1 verdicts (1 pass, 0 reject)", out)
        self.assertIn("unattributed escapes: 0", out)
        self.assertIn("undeclared steps: 0", out)

    def test_a_bad_since_is_refused(self):
        rc, _out, err = call(cli.cmd_review_yield, "--since", "yesterday")
        self.assertEqual(rc, 1)
        self.assertIn("YYYY-MM-DD", err)


if __name__ == "__main__":
    unittest.main()
