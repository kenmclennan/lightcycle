import unittest
from decimal import Decimal
from pathlib import Path

from scripts import mutation_ratchet as mr

ROOT = Path(__file__).resolve().parents[2]
PREFIXES = {"lightcycle.domain.money": "lightcycle/domain/money.py"}


class TestBaselineFormat(unittest.TestCase):
    def test_round_trip(self):
        scores = {"lightcycle/domain/b.py": Decimal("92.0"), "lightcycle/domain/a.py": Decimal("100.0")}
        text = mr.format_baseline(scores)
        self.assertEqual(text.splitlines()[0], "lightcycle/domain/a.py: 100.0")
        self.assertEqual(mr.parse_baseline(text), scores)

    def test_score_rounds_half_up_to_one_decimal(self):
        self.assertEqual(mr.score(23, 25), Decimal("92.0"))
        self.assertEqual(mr.score(22, 25), Decimal("88.0"))
        self.assertEqual(mr.score(1, 8), Decimal("12.5"))
        self.assertEqual(mr.score(1, 16), Decimal("6.3"))


class TestRatchetRule(unittest.TestCase):
    baseline = {"lightcycle/domain/money.py": Decimal("92.0")}

    def test_equal_to_baseline_passes(self):
        current = {"lightcycle/domain/money.py": mr.score(23, 25)}
        self.assertEqual(mr.below_baseline(current, self.baseline), [])

    def test_one_fewer_killed_fails(self):
        current = {"lightcycle/domain/money.py": mr.score(22, 25)}
        self.assertEqual(mr.below_baseline(current, self.baseline), ["lightcycle/domain/money.py"])

    def test_above_baseline_passes(self):
        current = {"lightcycle/domain/money.py": mr.score(25, 25)}
        self.assertEqual(mr.below_baseline(current, self.baseline), [])

    def test_module_absent_from_baseline_is_not_checked(self):
        current = {"lightcycle/domain/other.py": Decimal("0.0")}
        self.assertEqual(mr.below_baseline(current, self.baseline), [])


class TestScopedSelection(unittest.TestCase):
    baseline = {"lightcycle/domain/money.py", "lightcycle/domain/prose.py"}

    def test_changed_source_selects_and_changed_test_does_not(self):
        selected, unresolved = mr.select_modules(
            ["lightcycle/domain/money.py", "tests/unit/test_money.py"], self.baseline
        )
        self.assertEqual(selected, ["lightcycle/domain/money.py"])
        self.assertEqual(unresolved, ["tests/unit/test_money.py"])

    def test_all_resolved(self):
        selected, unresolved = mr.select_modules(sorted(self.baseline), self.baseline)
        self.assertEqual(selected, sorted(self.baseline))
        self.assertEqual(unresolved, [])

    def test_none_resolved(self):
        selected, unresolved = mr.select_modules(["README.md"], self.baseline)
        self.assertEqual(selected, [])
        self.assertEqual(unresolved, ["README.md"])

    def test_mixed_reports_the_unresolved_one(self):
        selected, unresolved = mr.select_modules(
            ["lightcycle/domain/money.py", "lightcycle/domain/prose.py", "docs/ontology.md"],
            self.baseline,
        )
        self.assertEqual(selected, ["lightcycle/domain/money.py", "lightcycle/domain/prose.py"])
        self.assertEqual(unresolved, ["docs/ontology.md"])


class TestParseResults(unittest.TestCase):
    def test_counts_killed_and_other_statuses_and_excludes_unchecked(self):
        text = "\n".join(
            [
                "    lightcycle.domain.money.x_a__mutmut_1: killed",
                "    lightcycle.domain.money.x_a__mutmut_2: survived",
                "    lightcycle.domain.money.x_a__mutmut_3: timeout",
                "    lightcycle.domain.money.x_a__mutmut_4: no tests",
                "    lightcycle.domain.money.x_a__mutmut_5: not checked",
                "    lightcycle.domain.money.x_a__mutmut_6: skipped",
                "    lightcycle.domain.other.x_b__mutmut_1: killed",
            ]
        )
        counts, excluded, timeouts = mr.parse_results(text, PREFIXES)
        self.assertEqual(counts, {"lightcycle/domain/money.py": (1, 3)})
        self.assertEqual(excluded, 3)
        self.assertEqual(timeouts, 1)

    def test_timeout_is_a_member_of_excluded(self):
        self.assertIn("timeout", mr.EXCLUDED)

    def test_module_whose_only_non_killed_mutant_timed_out_scores_100(self):
        text = "\n".join(
            [
                "    lightcycle.domain.money.x_a__mutmut_1: killed",
                "    lightcycle.domain.money.x_a__mutmut_2: timeout",
            ]
        )
        counts, _, timeouts = mr.parse_results(text, PREFIXES)
        self.assertEqual(timeouts, 1)
        self.assertEqual(mr.scores_from_counts(counts), {"lightcycle/domain/money.py": Decimal("100.0")})

    def test_a_killed_to_timeout_flip_still_fails_a_baseline_of_95_8(self):
        baseline = {"lightcycle/domain/money.py": Decimal("95.8")}
        self.assertEqual(mr.score(23, 24), Decimal("95.8"))
        self.assertEqual(mr.score(22, 23), Decimal("95.7"))
        self.assertEqual(
            mr.below_baseline({"lightcycle/domain/money.py": mr.score(22, 23)}, baseline),
            ["lightcycle/domain/money.py"],
        )

    def test_method_mutant_names_resolve_to_their_module(self):
        text = "    lightcycle.domain.money.xǁMoneyǁadd__mutmut_1: killed"
        counts, _, _ = mr.parse_results(text, PREFIXES)
        self.assertEqual(counts, {"lightcycle/domain/money.py": (1, 1)})

    def test_module_without_mutants_has_no_score(self):
        self.assertEqual(mr.scores_from_counts({"lightcycle/domain/money.py": (0, 0)}), {})


class TestCommittedBaseline(unittest.TestCase):
    def test_every_line_parses_and_names_an_existing_file(self):
        text = mr.BASELINE.read_text()
        scores = mr.parse_baseline(text)
        self.assertEqual(len(scores), len(text.splitlines()))
        for module, value in scores.items():
            self.assertTrue((ROOT / module).is_file(), module)
            self.assertTrue(Decimal("0") <= value <= Decimal("100"), module)
