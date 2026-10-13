import unittest

from lightcycle.domain.guidance.guidance import (
    ENTRY, MALFORMED, NOT_GUIDANCE, GuidanceEntry, classify, fill, matches, matches_step_key,
    order, parse_citation, render_section,
)


def _meta(**over):
    meta = {
        "type": "Guidance",
        "status": "stable",
        "verified": "ken 2026-10-01",
        "applies-to": {"facets": "[kotlin, spring-boot]", "steps": "[write-code, acme/review-code]"},
    }
    meta.update(over)
    return meta


def _entry(entry_id="a", facets=(), steps=(), body="x"):
    return GuidanceEntry(entry_id, "stable", True, tuple(facets), tuple(steps), body)


class TestClassify(unittest.TestCase):
    def test_a_stable_verified_entry_is_a_candidate_with_parsed_lists(self):
        c = classify("testing/a", _meta(), "body text\n\n")
        self.assertEqual(c.kind, ENTRY)
        self.assertTrue(c.entry.is_candidate())
        self.assertEqual(c.entry.facets, ("kotlin", "spring-boot"))
        self.assertEqual(c.entry.steps, ("write-code", "acme/review-code"))
        self.assertEqual(c.entry.body, "body text")

    def test_draft_deprecated_and_other_statuses_are_not_candidates(self):
        for status in ("draft", "deprecated", "", "weird"):
            c = classify("a", _meta(status=status), "b")
            self.assertEqual(c.kind, ENTRY)
            self.assertFalse(c.entry.is_candidate(), status)

    def test_missing_or_empty_verified_is_not_a_candidate(self):
        for verified in ("", "   ", {}):
            c = classify("a", _meta(verified=verified), "b")
            self.assertFalse(c.entry.is_candidate())
        meta = _meta()
        del meta["verified"]
        self.assertFalse(classify("a", meta, "b").entry.is_candidate())

    def test_no_applies_to_is_malformed(self):
        meta = _meta()
        del meta["applies-to"]
        self.assertEqual(classify("a", meta, "b").kind, MALFORMED)

    def test_scalar_applies_to_is_malformed(self):
        self.assertEqual(classify("a", _meta(**{"applies-to": "everything"}), "b").kind, MALFORMED)

    def test_block_list_and_empty_value_lists_are_malformed(self):
        for value in ("", {}, "kotlin", "[kotlin"):
            meta = _meta(**{"applies-to": {"facets": value}})
            self.assertEqual(classify("a", meta, "b").kind, MALFORMED, repr(value))

    def test_empty_list_and_empty_applies_to_mean_everything(self):
        c = classify("a", _meta(**{"applies-to": {"facets": "[]", "steps": "[ ]"}}), "b")
        self.assertEqual((c.entry.facets, c.entry.steps), ((), ()))
        c = classify("a", _meta(**{"applies-to": {}}), "b")
        self.assertEqual(c.kind, ENTRY)

    def test_other_or_missing_type_is_not_guidance(self):
        self.assertEqual(classify("a", _meta(type="Concept"), "b").kind, NOT_GUIDANCE)
        self.assertEqual(classify("a", {}, "b").kind, NOT_GUIDANCE)


class TestMatching(unittest.TestCase):
    def test_every_listed_facet_must_be_declared(self):
        e = _entry(facets=("kotlin", "spring"))
        self.assertTrue(matches(e, ("kotlin", "spring", "x"), "s", None))
        self.assertFalse(matches(e, ("kotlin",), "s", None))

    def test_no_facets_matches_a_project_with_none(self):
        self.assertTrue(matches(_entry(), (), "s", None))

    def test_facet_entry_does_not_match_the_empty_facet_project(self):
        self.assertFalse(matches(_entry(facets=("kotlin",)), (), "s", None))

    def test_no_steps_matches_every_step(self):
        self.assertTrue(matches(_entry(), (), "anything", None))

    def test_bare_step_matches_in_any_origin_and_without_one(self):
        e = _entry(steps=("write-code",))
        self.assertTrue(matches(e, (), "write-code", "acme"))
        self.assertTrue(matches(e, (), "write-code", None))
        self.assertFalse(matches(e, (), "review-code", "acme"))

    def test_origin_scoped_step_matches_only_that_origin(self):
        e = _entry(steps=("acme/write-code",))
        self.assertTrue(matches(e, (), "write-code", "acme"))
        self.assertFalse(matches(e, (), "write-code", "other"))
        self.assertFalse(matches(e, (), "write-code", None))

    def test_any_listed_step_is_enough(self):
        e = _entry(steps=("a", "acme/b"))
        self.assertTrue(matches(e, (), "b", "acme"))

    def test_step_key_rule_for_doctor(self):
        self.assertTrue(matches_step_key(_entry(), None))
        self.assertFalse(matches_step_key(_entry(steps=("a",)), None))
        self.assertTrue(matches_step_key(_entry(steps=("acme/a",)), "a"))
        self.assertFalse(matches_step_key(_entry(steps=("a",)), "acme/a"))
        self.assertTrue(matches_step_key(_entry(steps=("acme/a",)), "acme/a"))


class TestOrderAndFill(unittest.TestCase):
    def test_step_naming_entries_come_first_then_by_id(self):
        entries = [_entry("z"), _entry("b", steps=("s",)), _entry("a"), _entry("c", steps=("s",))]
        self.assertEqual([e.id for e in order(entries)], ["b", "c", "a", "z"])

    def test_worked_example_skips_whole_and_continues(self):
        entries = [
            _entry("a", body="x" * 60), _entry("b", body="x" * 50),
            _entry("c", body="x" * 40), _entry("d", body="x"),
        ]
        delivered, skipped = fill(entries, 100)
        self.assertEqual([e.id for e in delivered], ["a", "c"])
        self.assertEqual([e.id for e in skipped], ["b", "d"])

    def test_budget_counts_utf8_bytes(self):
        delivered, skipped = fill([_entry("a", body="é" * 3)], 5)
        self.assertEqual((delivered, [e.id for e in skipped]), ([], ["a"]))

    def test_zero_budget_delivers_nothing(self):
        delivered, skipped = fill([_entry("a")], 0)
        self.assertEqual((delivered, len(skipped)), ([], 1))


class TestRenderSection(unittest.TestCase):
    def test_section_text_is_pinned(self):
        text = render_section([_entry("testing/a", body="first"), _entry("ci/b", body="second")], "LC-1.2")
        self.assertEqual(
            text,
            "## Guidance for this project\n\n"
            "These entries come from the user's guidance repo. Cite an entry by its id.\n\n"
            "### testing/a\n\nfirst\n\n### ci/b\n\nsecond\n\n"
            "When an entry above changed what you did, cite it before you finish: run "
            "`lc attach LC-1.2 guidance-cited \"<id>[, <id>...]\"` once, listing every entry you "
            "applied. Cite only entries that changed what you did, never one you only read.",
        )


class TestParseCitation(unittest.TestCase):
    def test_parse_shapes(self):
        self.assertEqual(parse_citation("a, b"), ["a", "b"])
        self.assertEqual(parse_citation("a,b"), ["a", "b"])
        self.assertEqual(parse_citation("a, a, b"), ["a", "b"])
        self.assertEqual(parse_citation(",  ,"), [])
        self.assertEqual(parse_citation("a/b"), ["a/b"])


class TestClassifyRetirementFields(unittest.TestCase):
    def test_covers_and_stale_after_are_populated(self):
        r = classify("a/b", _meta(covers="https://github.com/x/y/issues/1", stale_after="2027-01-01"), "body")
        self.assertEqual(r.kind, ENTRY)
        self.assertEqual(r.entry.covers, "https://github.com/x/y/issues/1")
        self.assertEqual(r.entry.stale_after, "2027-01-01")

    def test_absent_fields_are_blank(self):
        r = classify("a/b", _meta(), "body")
        self.assertEqual(r.entry.covers, "")
        self.assertEqual(r.entry.stale_after, "")


if __name__ == "__main__":
    unittest.main()
