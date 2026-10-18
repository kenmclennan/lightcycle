import io
import json
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from lightcycle import cli
from lightcycle.application.inspect.resolve_references import ResolveReferencesUseCase
from lightcycle.domain.prose import (
    BODY,
    HEADING,
    Link,
    Literal,
    Reference,
    parse_prose,
    reference_ids,
)
from tests.support.fake_store import FakeStore


class TestParseProse(unittest.TestCase):
    def test_all_six_heading_levels_collapse_to_one_kind_with_the_markers_removed(self):
        for level in range(1, 7):
            line = parse_prose("%s Title" % ("#" * level))[0]
            self.assertEqual((line.kind, line.segments), (HEADING, (Literal("Title"),)))

    def test_a_hash_with_no_space_is_body(self):
        line = parse_prose("#hashtag")[0]
        self.assertEqual((line.kind, line.segments), (BODY, (Literal("#hashtag"),)))

    def test_seven_hashes_is_body(self):
        self.assertEqual(parse_prose("####### x")[0].kind, BODY)

    def test_fenced_lines_and_the_fences_are_body_and_never_parsed(self):
        lines = parse_prose("```sh\n# note [[LC-1]]\n```\n## After")
        self.assertEqual([l.kind for l in lines], [BODY, BODY, BODY, HEADING])
        self.assertEqual(lines[1].segments, (Literal("# note [[LC-1]]"),))

    def test_item_step_and_goal_ids_parse_as_references(self):
        for ref in ("LC-861", "LC-878.1", "G-1"):
            self.assertEqual(parse_prose("[[%s]]" % ref)[0].segments, (Reference(ref),))

    def test_non_ids_and_labelled_links_stay_literal(self):
        for text in ("[[not an id]]", "[[LC-861|label]]", "[[861]]"):
            self.assertEqual(parse_prose(text)[0].segments, (Literal(text),))

    def test_a_reference_inside_a_heading_is_a_reference(self):
        line = parse_prose("## See [[LC-1]] now")[0]
        self.assertEqual(line.kind, HEADING)
        self.assertEqual(
            line.segments, (Literal("See "), Reference("LC-1"), Literal(" now"))
        )

    def test_blank_lines_and_order_are_preserved(self):
        lines = parse_prose("a\n\n## b\n\nc")
        self.assertEqual([l.kind for l in lines], [BODY, BODY, HEADING, BODY, BODY])
        self.assertEqual(lines[1].segments, (Literal(""),))

    def test_reference_ids_are_distinct_in_order(self):
        lines = parse_prose("[[LC-2]] [[LC-1]]\n## [[LC-2]]")
        self.assertEqual(reference_ids(lines), ["LC-2", "LC-1"])


class TestProseLinksAndLists(unittest.TestCase):
    def test_list_lines_keep_marker_and_indent(self):
        lines = parse_prose("- one\n  * two\n    1. three")

        self.assertEqual(
            [(l.kind, l.segments) for l in lines],
            [
                (BODY, (Literal("- one"),)),
                (BODY, (Literal("  * two"),)),
                (BODY, (Literal("    1. three"),)),
            ],
        )

    def test_a_bare_url_parses_to_a_link(self):
        (line,) = parse_prose("see https://example.test/a?b=1, then go")

        self.assertEqual(
            line.segments,
            (Literal("see "), Link("https://example.test/a?b=1", "https://example.test/a?b=1"), Literal(", then go")),
        )

    def test_a_markdown_link_parses_to_label_and_url(self):
        (line,) = parse_prose("read [the spec](https://example.test/spec) now")

        self.assertEqual(
            line.segments,
            (Literal("read "), Link("the spec", "https://example.test/spec"), Literal(" now")),
        )

    def test_a_url_inside_a_fence_stays_literal(self):
        lines = parse_prose("```\nhttps://example.test/x\n```")

        self.assertEqual(lines[1].segments, (Literal("https://example.test/x"),))

    def test_a_heading_containing_a_link_yields_both_kinds(self):
        (line,) = parse_prose("## See [docs](https://example.test/d)")

        self.assertEqual(line.kind, HEADING)
        self.assertEqual(line.segments, (Literal("See "), Link("docs", "https://example.test/d")))


class TestResolveReferences(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        self.item = self.store.create_item("the item title", "d")
        self.goal = self.store.create_goal("the goal title")

    def test_resolves_an_item_and_a_goal_and_maps_a_dead_id_to_none(self):
        result = ResolveReferencesUseCase(self.store).execute(
            [self.item, self.goal, "LC-9999", self.item]
        )
        self.assertEqual(
            result, {self.item: "the item title", self.goal: "the goal title", "LC-9999": None}
        )

    def test_an_empty_title_is_unresolved(self):
        empty = self.store.create_item("", "d")
        self.assertEqual(ResolveReferencesUseCase(self.store).execute([empty]), {empty: None})


class TestCliStaysRaw(unittest.TestCase):
    def setUp(self):
        self._orig = cli._container
        self.addCleanup(lambda: cli.set_container(self._orig))
        self.store = FakeStore()
        self.store.add_project("acme/lightcycle")
        self.item = self.store.create_item("an item", "## x\n\nsee [[LC-1]]")
        cli.set_container(SimpleNamespace(store=self.store, flow_service=lambda: None))

    def test_goal_show_prints_the_description_verbatim(self):
        gid = self.store.create_goal("g", "## x\n\nsee [[LC-1]]", "lightcycle")
        out = io.StringIO()
        with redirect_stdout(out):
            cli.cmd_goal(["show", gid])
        self.assertIn("description:\n## x\n\nsee [[LC-1]]\n", out.getvalue())

    def test_show_json_carries_the_description_unchanged(self):
        out = io.StringIO()
        with patch.object(cli, "_flow", return_value=MagicMock(step_skill=lambda s: None, workflow_owner=lambda s: (None, None))), redirect_stdout(out):
            cli.cmd_show([self.item])
        self.assertEqual(json.loads(out.getvalue())["description"], "## x\n\nsee [[LC-1]]")
