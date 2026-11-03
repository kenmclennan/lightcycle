import unittest

from lightcycle.domain.guidance.budget import heaviest_universal_step, is_universal, overflows
from lightcycle.domain.guidance.guidance import GuidanceEntry

STEP = ("lightcycle", "write-code")


def _e(id_, size, steps=(), facets=()):
    return GuidanceEntry(
        id=id_, status="stable", verified="k", facets=tuple(facets),
        steps=tuple(steps), body="x" * size)


class TestOverflows(unittest.TestCase):
    def _run(self, entries, budget=100, projects=(("p", ()),), steps=(STEP,)):
        return overflows(entries, list(projects), list(steps), budget)

    def test_entry_that_does_not_fit_is_skipped_and_total_reported(self):
        found = self._run([_e("a", 60, ["write-code"]), _e("b", 40), _e("c", 1)])
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].skipped, ("c",))
        self.assertEqual(found[0].matched_bytes, 101)
        self.assertEqual(found[0].step, "lightcycle/write-code")
        self.assertEqual(found[0].budget, 100)

    def test_total_exactly_on_the_budget_is_not_an_overflow(self):
        self.assertEqual(self._run([_e("a", 60, ["write-code"]), _e("b", 40)]), [])

    def test_walk_continues_past_a_skipped_entry(self):
        found = self._run([
            _e("a", 60, ["write-code"]), _e("b", 50), _e("c", 30), _e("d", 10)])
        self.assertEqual(found[0].skipped, ("b",))
        self.assertEqual(found[0].matched_bytes, 150)

    def test_entries_for_another_facet_never_overflow_a_project(self):
        self.assertEqual(self._run([_e("a", 600, facets=["python"])]), [])

    def test_only_the_overflowing_project_is_returned(self):
        entries = [_e("a", 60, facets=["python"]), _e("b", 60, facets=["python"])]
        found = self._run(entries, projects=[("py", ("python",)), ("kt", ("kotlin",))])
        self.assertEqual([o.project for o in found], ["py"])
        self.assertEqual(found[0].skipped, ("b",))

    def test_origin_qualified_step_matches_only_its_origin(self):
        other = _e("a", 600, ["other-origin/write-code"])
        bare = _e("a", 600, ["write-code"])
        self.assertEqual(self._run([other]), [])
        self.assertEqual(len(self._run([bare, _e("b", 10)])), 1)

    def test_unscoped_overflow_is_reported_at_every_step(self):
        steps = [("o", "a"), ("o", "b")]
        found = self._run([_e("x", 60), _e("y", 60)], steps=steps)
        self.assertEqual([o.step for o in found], ["o/a", "o/b"])


def _status(id_, status, facets=(), steps=()):
    return GuidanceEntry(
        id=id_, status=status, verified="k", facets=tuple(facets),
        steps=tuple(steps), body="x")


class TestIsUniversal(unittest.TestCase):
    def test_stable_without_facets_is_universal_whatever_its_steps(self):
        self.assertTrue(is_universal(_status("a", "stable")))
        self.assertTrue(is_universal(_status("a", "stable", steps=["write-code"])))

    def test_faceted_entry_is_not_universal(self):
        self.assertFalse(is_universal(_status("a", "stable", facets=["kotlin"])))
        self.assertFalse(is_universal(_status("a", "stable", facets=["kotlin"], steps=["write-code"])))

    def test_draft_and_deprecated_are_never_universal(self):
        for status in ("draft", "deprecated"):
            self.assertFalse(is_universal(_status("a", status)))
            self.assertFalse(is_universal(_status("a", status, steps=["write-code"])))


class TestHeaviestUniversalStep(unittest.TestCase):
    A = ("o", "a")
    B = ("o", "b")

    def test_step_with_the_largest_matched_total_wins(self):
        entries = [_e("u1", 10), _e("u2", 30, ["a"]), _e("u3", 20, ["b"])]
        self.assertEqual(heaviest_universal_step(entries, [self.A, self.B]), ("o/a", 40))
        entries = [_e("u1", 10), _e("u2", 20, ["a"]), _e("u3", 30, ["b"])]
        self.assertEqual(heaviest_universal_step(entries, [self.A, self.B]), ("o/b", 40))

    def test_tie_goes_to_the_first_step(self):
        entries = [_e("u1", 10)]
        self.assertEqual(heaviest_universal_step(entries, [self.B, self.A]), ("o/b", 10))

    def test_faceted_and_draft_entries_are_not_counted(self):
        entries = [_e("u1", 10), _e("f", 50, facets=["kotlin"])]
        self.assertEqual(heaviest_universal_step(entries, [self.A]), ("o/a", 10))

    def test_no_steps_sums_every_universal_entry(self):
        entries = [_e("u1", 10), _e("u2", 30, ["a"]), _e("f", 50, facets=["kotlin"])]
        self.assertEqual(heaviest_universal_step(entries, []), (None, 40))
