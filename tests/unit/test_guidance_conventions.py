import unittest

from lightcycle.domain.guidance.conventions import (
    CONVENTIONS_TEXT,
    CONVENTIONS_VERSION,
    check_entries,
    is_checked_path,
    item_ids,
    parse,
)


def entry(status="draft", applies="  facets: [kotlin]\n  steps: [write-code]", extra="",
          purpose="p", when="w", why="y", body="body\n", applies_block=True):
    front = "type: Guidance\n"
    if applies_block:
        front += "applies-to:\n%s\n" % applies
    front += "status: %s\n" % status
    for key, value in (("purpose", purpose), ("when", when), ("why", why)):
        if value is not None:
            front += "%s: %s\n" % (key, value)
    front += extra
    return "---\n%s---\n%s" % (front, body)


class Tree:
    def __init__(self, head, base=None, pages=("kotlin",)):
        self.head = head
        self.base = base or {}
        self.pages = set(pages)

    def check(self, mode, deleted=()):
        return check_entries(
            mode, list(self.head), list(deleted), self.pages,
            lambda p: self.head[p], lambda p: self.base.get(p),
        )


class TestConventionsText(unittest.TestCase):
    def test_version_line_follows_the_title(self):
        lines = CONVENTIONS_TEXT.splitlines()
        self.assertEqual(lines[0], "# Conventions")
        self.assertEqual(lines[2], "Conventions version: %d" % CONVENTIONS_VERSION)
        self.assertEqual(CONVENTIONS_VERSION, 2)

    def test_text_names_every_rule_and_no_item_id(self):
        self.assertEqual(item_ids(CONVENTIONS_TEXT), [])
        self.assertIn("## Checks", CONVENTIONS_TEXT)
        for n in range(1, 11):
            self.assertIn("\n%d. " % n, CONVENTIONS_TEXT)
        self.assertNotIn("\n11. ", CONVENTIONS_TEXT)
        for word in ("purpose", "when", "why", "item id"):
            self.assertIn(word, CONVENTIONS_TEXT)

    def test_text_is_version_two_and_drops_the_verified_rules(self):
        self.assertIn("Conventions version: 2", CONVENTIONS_TEXT)
        for removed in (
            "fails unless the entry is context-only",
            "with an empty or missing `verified` fails",
            "Context-only means",
        ):
            self.assertNotIn(removed, CONVENTIONS_TEXT)


class TestParsingEdges(unittest.TestCase):
    def test_utf_and_sha_are_not_item_ids(self):
        self.assertEqual(item_ids("UTF-8 and SHA-256"), [])

    def test_dotted_item_id_is_matched_whole(self):
        self.assertEqual(item_ids("see LC-12.3 now"), ["LC-12.3"])

    def test_dash_line_in_front_matter_is_skipped(self):
        self.assertEqual(parse("---\ntype: X\n- a\n---\n"), ({"type": "X"}, {}))

    def test_front_matter_line_without_colon_is_malformed(self):
        self.assertIsNone(parse("---\ntype X\n---\n"))

    def test_checked_path_skips_index_and_conventions(self):
        self.assertFalse(is_checked_path("index.md"))
        self.assertFalse(is_checked_path("a/CONVENTIONS.md"))
        self.assertFalse(is_checked_path("a/b.txt"))
        self.assertTrue(is_checked_path("a/b.md"))


class TestBothModes(unittest.TestCase):
    def test_clean_entry_passes_in_both_modes(self):
        for mode in ("draft", "final"):
            self.assertEqual(Tree({"a.md": entry()}).check(mode), [])

    def test_rule_1_deleted_guidance_entry_fails(self):
        tree = Tree({}, base={"a.md": entry()})
        self.assertEqual(
            tree.check("final", deleted=["a.md"]),
            ["a.md: entry deleted - retire it with status: deprecated instead"],
        )

    def test_rule_1_deleted_non_guidance_page_is_ignored(self):
        tree = Tree({}, base={"a.md": "---\ntitle: x\n---\n"})
        self.assertEqual(tree.check("final", deleted=["a.md"]), [])

    def test_rule_2_front_matter_missing_unclosed_or_malformed(self):
        for text in ("no front matter\n", "---\ntype: Guidance\n", "---\nbroken\n---\n"):
            self.assertEqual(
                Tree({"a.md": text}).check("final"),
                ["a.md: front matter missing or malformed"],
            )

    def test_rule_3_no_applies_to(self):
        self.assertEqual(
            Tree({"a.md": entry(applies_block=False)}).check("final"),
            ["a.md: no applies-to mapping"],
        )

    def test_rule_4_facets_and_steps_must_be_inline_lists(self):
        text = entry(applies="  facets: kotlin\n  steps: write-code")
        self.assertEqual(
            Tree({"a.md": text}).check("final"),
            [
                "a.md: applies-to facets must be an inline list on one line",
                "a.md: applies-to steps must be an inline list on one line",
            ],
        )

    def test_rule_5_facet_without_page(self):
        text = entry(applies="  facets: [kotlin, rust]")
        self.assertEqual(
            Tree({"a.md": text}).check("final"),
            ["a.md: facet 'rust' has no concept page rust.md"],
        )

    def test_rule_5_all_facets_found(self):
        text = entry(applies="  facets: [kotlin, rust]")
        self.assertEqual(Tree({"a.md": text}, pages=("kotlin", "rust")).check("final"), [])

    def test_rule_5_no_facets_found(self):
        text = entry(applies="  facets: [kotlin, rust]")
        self.assertEqual(
            Tree({"a.md": text}, pages=()).check("final"),
            [
                "a.md: facet 'kotlin' has no concept page kotlin.md",
                "a.md: facet 'rust' has no concept page rust.md",
            ],
        )

    def test_rule_6_step_shape(self):
        text = entry(applies="  steps: [write-code, lightcycle/write-code, Bad_Step, a/b/c]")
        self.assertEqual(
            Tree({"a.md": text}).check("final"),
            [
                "a.md: step 'Bad_Step' is not <step> or <origin>/<step>",
                "a.md: step 'a/b/c' is not <step> or <origin>/<step>",
            ],
        )

    def test_rule_7_status_values(self):
        self.assertEqual(
            Tree({"a.md": entry(status="live")}).check("final"),
            ["a.md: status 'live' is not draft, stable or deprecated"],
        )

    def test_rule_8_missing_or_empty_context_fields(self):
        text = entry(purpose=None, when="", why="y")
        self.assertEqual(
            Tree({"a.md": text}).check("final"),
            [
                "a.md: missing or empty front-matter field 'purpose'",
                "a.md: missing or empty front-matter field 'when'",
            ],
        )

    def test_rule_9_item_id_per_match(self):
        text = entry(body="LC-1 and LC-2.3 but UTF-8\n")
        self.assertEqual(
            Tree({"a.md": text}).check("final"),
            [
                "a.md: names item id 'LC-1' - record its origin on the item's finding artifact instead",
                "a.md: names item id 'LC-2.3' - record its origin on the item's finding artifact instead",
            ],
        )

    def test_rule_10_stray_page_fails_unless_named_as_facet(self):
        stray = "---\ntitle: x\n---\n"
        self.assertEqual(
            Tree({"other.md": stray}).check("final"),
            ["other.md: no type: Guidance and no entry names it as a facet"],
        )
        self.assertEqual(
            Tree({"a.md": entry(), "dir/kotlin.md": stray}).check("final"), [],
        )


class TestVerifiedAndStatusAreNoLongerChecked(unittest.TestCase):
    def test_stable_in_draft_mode_passes(self):
        self.assertEqual(Tree({"a.md": entry(status="stable")}).check("draft"), [])

    def test_a_verified_key_in_draft_mode_passes(self):
        self.assertEqual(Tree({"a.md": entry(extra="verified: ken\n")}).check("draft"), [])

    def test_stable_without_verified_in_final_mode_passes(self):
        self.assertEqual(Tree({"a.md": entry(status="stable")}).check("final"), [])
        self.assertEqual(
            Tree({"a.md": entry(status="stable", extra="verified:\n")}).check("final"), [])

    def test_stable_with_verified_is_clean(self):
        self.assertEqual(
            Tree({"a.md": entry(status="stable", extra="verified: ken\n")}).check("final"), [],
        )

    def test_draft_and_final_return_identical_failures_for_the_same_inputs(self):
        head = {
            "a.md": entry(status="stable", extra="verified: ken\n", why=None),
            "b.md": entry(applies="  facets: [rust]", body="LC-1\n"),
        }
        tree = Tree(head)
        self.assertNotEqual(tree.check("draft"), [])
        self.assertEqual(tree.check("draft"), tree.check("final"))
