import unittest

from lightcycle.domain.work import (
    MAX_PARAGRAPHS,
    MAX_SENTENCE_WORDS,
    MAX_SENTENCES_PER_PARAGRAPH,
    MAX_WORDS,
    cap_breaches,
    render_cap_refusal,
)

NOTE_LC_935_2 = (
    "Added resolves and resolved-by to _ATTACH_FORBIDDEN_TYPES. resolved-by is not read by "
    "anything that closes items, but it is the same kind of engine-written internal artifact, "
    "so a worker forging it is refused too."
)
NOTE_LC_830_6 = (
    "Rework for the CI integration failure: no code change, the same single commit is "
    "re-handed back. The failing test, "
    "test_worker_group_reap.py::test_prune_reaps_a_dead_workers_orphaned_child, is unrelated "
    "to this diff (cli.py, cli_commands.py, one simulate test). It passed locally, and the "
    "full suite was green (5478 passed) with ruff clean. Probable flake in the reap test's "
    "30s polling window; worth a separate look. No tests removed or restored."
)
NOTE_LC_899_9 = (
    "Full-suite run could not be observed (timeout/lost background output); ran unit tests "
    "matching goal/hub/screen_render/heading/prose/tui: 839 passed, ruff clean. Deviation: "
    "_refresh sets _last_key even while a hidden pane is unsized (hidden panes are always "
    "width 0); sections skip rendering at width 0 and width is in the key so the sized paint "
    "follows."
)
NOTE_LC_931_2 = (
    "LC-851 is a new step 3 bullet; LC-829 is one sentence at the step 4 prettier "
    "instruction; LC-912 and LC-926 are one rewritten sentence in the count-verification "
    "bullet, with a pointer from the call-site-audit bullet. None was already resolved and "
    "none conflicted. LC-666 was not touched, as briefed."
)
NOTE_LC_602_8 = (
    "Add a mechanical/pinning test (e.g. extend tests/unit/test_architecture.py's AST-based "
    "pattern, following the existing import-direction checks there) asserting "
    "lightcycle/domain/ contains no currency/elapsed/TUI-label formatter and composes no "
    "lc-prefixed command string. Everything else in the PR checked out clean (tests green, "
    "ruff clean, structural moves match spec, refusal messages byte-identical) - this is the "
    "only gap."
)
NOTE_LC_738_18 = (
    "Engine blocker resolved: ENGINE_PIN 109cd62 and the installed engine (0.6.187) both "
    "carry LC-780's _forced_repeat_walk fix. Re-ran the full gate fresh: "
    "check/simulate/describe --mermaid pass clean for all five bundles. No code changes this "
    "pass beyond amending the commit body to drop the stale park narrative - Family 2 was "
    "already fully implemented."
)
NOTE_LC_432_5 = (
    "Implements the spec's --unset design verbatim: blank-value refusal for "
    "title/description/project/workflow/label/notes/tried, --unset <field> (repeatable) for "
    "description/project/workflow/notes, added to _SET_FORBIDDEN_FLAGS and "
    "_SET_FLAG_OWNERS. Updated the 3 pre-existing tests named in the spec's Testing section "
    "and added the full new test matrix plus 2 worker-mode tests. Docs (ontology.md, "
    "README.md) updated. bash tests/run.sh: 3222 passed; ruff clean."
)
NOTE_LC_867_7 = (
    "Apply the squash-paragraph sentence to all six steps carrying it, identically "
    "(steps/amend-writer.md, build-workflow.md, feature-writer.md, implement-features.md, "
    "scope-and-code.md, write-code.md - write-code already has it): 'commit it "
    "(`git commit`), then confirm `git rev-list --count origin/main..HEAD` is exactly `1` - "
    "a staged index is not a commit and `open-pr` has nothing to open a PR from, and the "
    "count is also not `1` when a later `--amend` rewrote an upstream commit'. Place it "
    "after the staging clause, before 'rebase over merge', matching LC-911's approach. "
    "Re-run the bundle gate (simulate) after."
)
NOTE_LC_901_7 = (
    "CLAUDE.md: in the 'One frame cannot certify a width-sensitive requirement' paragraph, "
    "drop the clause 'the harness tracks the requested width exactly, less the two frame "
    "columns' (unmeasured; pane text width is pane width less a variable scrollbar "
    "allowance). End that sentence at 'asserting the wrap moves with the terminal'. Fold "
    "into the squashed commit and force-push."
)


def _words(n, prefix="w"):
    return " ".join("%s%d" % (prefix, i) for i in range(n))


def _kinds(text):
    return [(b.rule, b.kind) for b in cap_breaches(text)]


class TestCeilingConstants(unittest.TestCase):
    def test_ceilings_match_the_standard(self):
        self.assertEqual(
            (MAX_PARAGRAPHS, MAX_WORDS, MAX_SENTENCES_PER_PARAGRAPH, MAX_SENTENCE_WORDS),
            (3, 180, 4, 30),
        )


class TestTheFourBounds(unittest.TestCase):
    def test_sentence_of_30_words_is_clean_and_31_breaches(self):
        self.assertEqual(cap_breaches(_words(30) + "."), ())
        self.assertEqual(_kinds(_words(31) + "."), [(3, "sentence")])

    def test_180_words_across_three_paragraphs_is_clean_and_181_breaches(self):
        def text(last_sentence_words):
            sentences = [_words(20, "a%d" % i) + "." for i in range(8)]
            sentences.append(_words(last_sentence_words, "z") + ".")
            return "\n\n".join(" ".join(sentences[i:i + 3]) for i in range(0, 9, 3))

        self.assertEqual(cap_breaches(text(20)), ())
        self.assertEqual(_kinds(text(21)), [(2, "words")])

    def test_three_paragraphs_is_clean_and_four_breaches(self):
        three = "\n\n".join("Short paragraph %d." % i for i in range(3))
        four = three + "\n\nShort paragraph 3."
        self.assertEqual(cap_breaches(three), ())
        self.assertEqual(_kinds(four), [(2, "paragraphs")])

    def test_four_sentences_in_a_paragraph_is_clean_and_five_breaches(self):
        four = " ".join("Sentence number %d here." % i for i in range(4))
        five = four + " Sentence number 4 here."
        self.assertEqual(cap_breaches(four), ())
        self.assertEqual(_kinds(five), [(2, "sentences")])

    def test_empty_and_none_are_clean(self):
        self.assertEqual(cap_breaches(""), ())
        self.assertEqual(cap_breaches(None), ())


class TestCountingRules(unittest.TestCase):
    def test_fenced_block_is_not_counted(self):
        text = "Short lead.\n\n```\n%s\n```\n\nShort tail." % _words(200)
        self.assertEqual(cap_breaches(text), ())

    def test_unclosed_fence_swallows_the_rest(self):
        self.assertEqual(cap_breaches("Lead.\n\n```\n%s" % _words(200)), ())

    def test_single_newline_is_not_a_paragraph_break(self):
        text = "\n".join("Line %d of one paragraph." % i for i in range(4))
        self.assertEqual(cap_breaches(text), ())
        many_lines = "\n".join("line %d" % i for i in range(10)) + "."
        self.assertEqual(cap_breaches(many_lines), ())

    def test_blank_lines_with_spaces_break_paragraphs(self):
        text = "One.\n  \nTwo.\n\n\n\nThree.\n\nFour."
        self.assertEqual(_kinds(text), [(2, "paragraphs")])

    def test_inline_code_span_is_one_word_and_never_split(self):
        text = "Run `%s` now." % _words(40)
        self.assertEqual(cap_breaches(text), ())

    def test_code_span_holding_a_full_stop_and_space_does_not_split(self):
        text = "First `a. b. c. d. e. f.` then more."
        self.assertEqual(cap_breaches(text), ())

    def test_paths_ids_versions_and_abbreviations_do_not_end_a_sentence(self):
        text = " ".join(
            ["See cli.py:123 and LC-909 in 0.6.264, e.g. the cache, i.e. the store, vs. the "
             "old path, cf. the note, approx. ten more"] + ["word"] * 20
        ) + "."
        self.assertEqual(_kinds(text), [(3, "sentence")])

    def test_bare_enumerator_does_not_end_a_sentence(self):
        text = "Steps: 1. read %s (3) done." % _words(26)
        self.assertEqual(_kinds(text), [(3, "sentence")])

    def test_lower_case_identifier_after_a_full_stop_starts_a_new_sentence(self):
        text = "%s. resolved_by is %s." % (_words(20), _words(20, "x"))
        self.assertEqual(cap_breaches(text), ())

    def test_semicolon_colon_and_hyphen_do_not_end_a_sentence(self):
        text = "%s; %s: %s - %s." % (_words(8), _words(8), _words(8), _words(8))
        self.assertEqual(_kinds(text), [(3, "sentence")])

    def test_bare_punctuation_tokens_are_not_words(self):
        text = "%s - -> | %s." % (_words(15), _words(15, "y"))
        self.assertEqual(cap_breaches(text), ())

    def test_list_items_are_separate_sentences(self):
        text = "\n".join("- item %s" % _words(20, "i%d" % n) for n in range(5))
        self.assertEqual(_kinds(text), [(2, "sentences")])

    def test_numbered_list_markers_start_sentences_and_are_not_words(self):
        text = "\n".join("%d. %s" % (n, _words(29)) for n in range(1, 4))
        self.assertEqual(cap_breaches(text), ())


class TestQuotedText(unittest.TestCase):
    def test_double_quoted_instruction_is_not_counted_like_the_same_text_in_backticks(self):
        lead = "Apply this sentence to all six steps, unchanged:"
        quoted = '%s "%s".' % (lead, _words(43))
        ticked = "%s `%s`." % (lead, _words(43))
        self.assertEqual(cap_breaches(quoted), ())
        self.assertEqual(cap_breaches(ticked), ())

    def test_double_quoted_span_holding_full_stops_does_not_split(self):
        text = 'He wrote "a. b. c. d. e. f." then %s.' % _words(20)
        self.assertEqual(cap_breaches(text), ())

    def test_single_quoted_multi_word_span_is_not_counted(self):
        text = "Use 'first %s last' now." % _words(40)
        self.assertEqual(cap_breaches(text), ())

    def test_single_quoted_single_word_is_left_alone(self):
        text = "Use 'flag' %s." % _words(29)
        self.assertEqual(_kinds(text), [(3, "sentence")])

    def test_apostrophes_inside_words_do_not_open_a_span(self):
        text = "It's LC-867's note and we don't %s." % _words(28)
        self.assertEqual(_kinds(text), [(3, "sentence")])

    def test_unmatched_apostrophe_does_not_swallow_the_rest(self):
        text = "Wrap it in 'quotes for now. It's the one we don't %s." % _words(30)
        self.assertEqual(_kinds(text), [(3, "sentence")])

    def test_unmatched_double_quote_does_not_swallow_the_rest(self):
        text = 'Wrap it in "quotes for now. %s.' % _words(31)
        self.assertEqual(_kinds(text), [(3, "sentence")])

    def test_quote_does_not_join_paragraphs(self):
        text = 'One "two.\n\nthree" %s.' % _words(31)
        self.assertEqual(_kinds(text), [(3, "sentence")])

    def test_quote_holding_a_code_span_is_restored_in_full_in_an_excerpt(self):
        text = '%s "run `a b c` now" %s.' % (_words(20), _words(20, "z"))
        (breach,) = cap_breaches(text)
        self.assertIn('"run `a b c` now"', breach.excerpt)

    def test_lc_867_7_no_longer_breaches(self):
        self.assertEqual(cap_breaches(NOTE_LC_867_7), ())

    def test_lc_901_7_no_longer_breaches(self):
        self.assertEqual(cap_breaches(NOTE_LC_901_7), ())


class TestBreachDetail(unittest.TestCase):
    def test_long_sentence_carries_the_whole_sentence(self):
        sentence = _words(31) + "."
        (breach,) = cap_breaches("Short one. " + sentence)
        self.assertEqual((breach.rule, breach.count, breach.limit), (3, 31, 30))
        self.assertEqual(breach.excerpt, sentence)

    def test_long_sentence_quotes_code_spans_as_written(self):
        sentence = "Run `a b c` " + _words(30) + "."
        (breach,) = cap_breaches(sentence)
        self.assertIn("`a b c`", breach.excerpt)

    def test_crowded_paragraph_names_the_paragraph_and_its_opening_words(self):
        text = "Fine.\n\n" + " ".join("Sentence %s here." % _words(3, "s%d" % i) for i in range(5))
        (breach,) = cap_breaches(text)
        self.assertEqual((breach.rule, breach.paragraph, breach.count, breach.limit), (2, 2, 5, 4))
        self.assertEqual(len(breach.excerpt.split()), 10)
        self.assertTrue(breach.excerpt.startswith("Sentence s00 s01 s02 here."))


class TestRenderCapRefusal(unittest.TestCase):
    def test_clean_fields_render_nothing(self):
        self.assertEqual(render_cap_refusal([("--note", "Short."), ("--tried", None)]), "")

    def test_refusal_states_it_stored_nothing_and_says_shorten_not_drop(self):
        out = render_cap_refusal([("--note", _words(31) + ".")])
        self.assertTrue(out.startswith("refused:"))
        self.assertIn("nothing was stored", out)
        self.assertIn("Shorten the text and run the command again; do not drop it.", out)

    def test_rule_3_line_quotes_the_whole_sentence(self):
        sentence = _words(34) + "."
        line = render_cap_refusal([("--note", sentence)]).splitlines()[1]
        self.assertEqual(
            line, '--note, rule 3: a sentence of 34 words, at most 30: "%s"' % sentence
        )

    def test_sentences_line_quotes_ten_words_then_an_ellipsis(self):
        text = " ".join("Sentence %s here." % _words(2, "s%d" % i) for i in range(5))
        line = render_cap_refusal([("--note", text)]).splitlines()[1]
        self.assertTrue(line.startswith("--note, rule 2: paragraph 1 has 5 sentences, at most 4:"))
        self.assertTrue(line.endswith(' ..."'))

    def test_words_and_paragraphs_lines_carry_counts_only(self):
        paragraph = ". ".join(_words(10, "q%d" % i) for i in range(5))
        text = "\n\n".join([paragraph + "."] * 4)
        lines = render_cap_refusal([("--note", text)]).splitlines()[1:]
        self.assertIn("--note, rule 2: 200 words, at most 180", lines)
        self.assertIn("--note, rule 2: 4 paragraphs, at most 3", lines)

    def test_one_line_per_breach(self):
        text = "\n\n".join([_words(31) + "."] * 4)
        lines = render_cap_refusal([("--note", text)]).splitlines()[1:]
        self.assertEqual(len(lines), 5)

    def test_several_fields_are_covered_by_one_output_naming_each(self):
        out = render_cap_refusal([
            ("--needs", _words(31) + "."), ("--reason", "Fine."), ("--tried", _words(32) + "."),
        ])
        self.assertTrue(out.startswith("refused: --needs, --tried break"))
        self.assertIn("--needs, rule 3", out)
        self.assertIn("--tried, rule 3", out)
        self.assertNotIn("--reason", out)

    def test_output_has_no_emdash(self):
        self.assertNotIn(chr(0x2014), render_cap_refusal([("--note", _words(200) + ".")]))


class TestRealNotes(unittest.TestCase):
    def test_lc_935_2_complies_though_a_capital_rule_would_fuse_its_sentences(self):
        self.assertEqual(cap_breaches(NOTE_LC_935_2), ())

    def test_lc_830_6_breaches_sentences_per_paragraph_only(self):
        self.assertEqual(_kinds(NOTE_LC_830_6), [(2, "sentences")])

    def test_lc_899_9_breaches_rule_3(self):
        self.assertEqual(_kinds(NOTE_LC_899_9), [(3, "sentence")])
        self.assertEqual(cap_breaches(NOTE_LC_899_9)[0].count, 34)

    def test_lc_931_2_breaches_rule_3(self):
        self.assertEqual(_kinds(NOTE_LC_931_2), [(3, "sentence")])
        self.assertEqual(cap_breaches(NOTE_LC_931_2)[0].count, 35)

    def test_lc_602_8_complies_and_holds_a_dotted_abbreviation(self):
        self.assertEqual(cap_breaches(NOTE_LC_602_8), ())

    def test_lc_738_18_complies_and_holds_a_version_and_a_possessive_id(self):
        self.assertEqual(cap_breaches(NOTE_LC_738_18), ())

    def test_lc_432_5_complies_and_holds_paths_and_a_test_count(self):
        self.assertEqual(cap_breaches(NOTE_LC_432_5), ())


if __name__ == "__main__":
    unittest.main()
