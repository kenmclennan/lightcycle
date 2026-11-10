import datetime
import unittest

from lightcycle.domain.pool import ModelRates, ToolUsage, UsageResume
from tests.support.fake_store import FakeStore
from tests.support.sqlite_store_factory import make_sqlite_store
from tests.support.step_factory import create_owned_step
from tests.support.store_seed import (
    held_comment,
    held_comment_for_step,
    seed_attribution,
    seed_day_summary_claim,
    seed_usage,
)

RATES = ModelRates(input=2.0, output=10.0, cache_read=0.2, cache_write=2.5)


class StoreSeedBase:
    def make_store(self):
        raise NotImplementedError

    def _live(self, s, tid, tokens, cost, basis, thinking, rates_used=None,
              turn_count=0, tool_usage=None):
        s.record_live_usage(
            "sp", UsageResume(log_file="/l/seed.log"), tid, tokens[0], tokens[1], tokens[2], tokens[3], cost,
            basis, thinking, turn_count, tool_usage or {}, rates_used=rates_used,
        )

    def _usage_view(self, s, tid):
        t = s.get_node(tid)
        return (
            t.usage_input_tokens, t.usage_output_tokens, t.usage_cache_read_tokens,
            t.usage_cache_creation_tokens, t.usage_cost_usd, t.usage_cost_basis,
            t.usage_rates_used, t.usage_thinking_tokens, t.turn_count,
            s.tool_usage_for(tid),
        )

    def _pair(self, s):
        return create_owned_step(s, "seeded"), create_owned_step(s, "live")

    def test_seed_usage_twice_matches_two_record_live_usage_calls(self):
        s = self.make_store()
        seeded, live = self._pair(s)
        seed_usage(s, seeded, 10, 20, 30, 40, 1.5, "list", 5)
        seed_usage(s, seeded, 1, 2, 3, 4, 0.5, None, 2)
        self._live(s, live, (10, 20, 30, 40), 1.5, "list", 5)
        self._live(s, live, (1, 2, 3, 4), 0.5, None, 2)
        self.assertEqual(self._usage_view(s, seeded), self._usage_view(s, live))

    def test_seed_usage_none_basis_rates_and_thinking_keep_prior_values(self):
        s = self.make_store()
        seeded, live = self._pair(s)
        seed_usage(s, seeded, 1, 1, 1, 1, 1.0, "derived", 5, rates_used=RATES)
        seed_usage(s, seeded, 1, 1, 1, 1, 1.0, None, None, rates_used=None)
        self._live(s, live, (1, 1, 1, 1), 1.0, "derived", 5, rates_used=RATES)
        self._live(s, live, (1, 1, 1, 1), 1.0, None, None, rates_used=None)
        self.assertEqual(self._usage_view(s, seeded), self._usage_view(s, live))
        self.assertEqual(s.get_node(seeded).usage_cost_basis, "derived")
        self.assertEqual(s.get_node(seeded).usage_thinking_tokens, 5)

    def test_seed_usage_first_none_then_real_values_moves_off_null(self):
        s = self.make_store()
        tid = create_owned_step(s, "t")
        seed_usage(s, tid, 1, 1, 1, 1, 1.0, None, None)
        self.assertIsNone(s.get_node(tid).usage_thinking_tokens)
        seed_usage(s, tid, 1, 1, 1, 1, 1.0, "list", 5)
        self.assertEqual(s.get_node(tid).usage_thinking_tokens, 5)
        self.assertEqual(s.get_node(tid).usage_cost_basis, "list")

    def test_seed_usage_with_zero_tokens_still_records_the_basis(self):
        s = self.make_store()
        tid = create_owned_step(s, "t")
        seed_usage(s, tid, 0, 0, 0, 0, 0.0, "list", None)
        self.assertEqual(s.get_node(tid).usage_cost_basis, "list")

    def test_seed_usage_on_an_unknown_step_raises(self):
        s = self.make_store()
        with self.assertRaises(Exception):
            seed_usage(s, "no-such-step", 1, 1, 1, 1, 1.0, "list", None)

    def test_seed_attribution_twice_matches_two_record_live_usage_calls(self):
        s = self.make_store()
        seeded, live = self._pair(s)
        first = {"Read": ToolUsage(calls=2, bytes=100)}
        second = {"Read": ToolUsage(calls=1, bytes=50), "Grep": ToolUsage(calls=1, bytes=5)}
        seed_attribution(s, seeded, 3, first)
        seed_attribution(s, seeded, 1, second)
        self._live(s, live, (0, 0, 0, 0), 0.0, None, None, turn_count=3, tool_usage=first)
        self._live(s, live, (0, 0, 0, 0), 0.0, None, None, turn_count=1, tool_usage=second)
        self.assertEqual(self._usage_view(s, seeded), self._usage_view(s, live))
        self.assertEqual(s.get_node(seeded).turn_count, 4)

    def test_seed_attribution_leaves_usage_totals_untouched(self):
        s = self.make_store()
        tid = create_owned_step(s, "t")
        seed_usage(s, tid, 10, 20, 30, 40, 1.5, "derived", 5, rates_used=RATES)
        before = self._usage_view(s, tid)[:8]
        seed_attribution(s, tid, 2, {"Read": ToolUsage(calls=1, bytes=1)})
        self.assertEqual(self._usage_view(s, tid)[:8], before)

    def _hold(self, s, key, created_at):
        s.file_hold("R-1", key, "mallory", "do it", None, None, created_at)
        item = s.create_item("held", "d", shortcode="HLD")
        step = s.create_step(stage="review-held-comment", role="human", item=item)
        s.attach_hold("R-1", key, item, step)
        return step

    def test_held_comment_returns_each_state_and_none_for_an_absent_key(self):
        s = self.make_store()
        approved = self._hold(s, "mention:1", 1.0)
        self._hold(s, "mention:2", 2.0)
        rejected = self._hold(s, "mention:3", 3.0)
        s.decide_hold(approved, "approved")
        s.mark_hold_dispatched("R-1", "mention:1")
        s.decide_hold(rejected, "rejected")
        self.assertEqual(held_comment(s, "R-1", "mention:1").state, "dispatched")
        self.assertEqual(held_comment(s, "R-1", "mention:2").state, "held")
        self.assertEqual(held_comment(s, "R-1", "mention:3").state, "rejected")
        self.assertIsNone(held_comment(s, "R-1", "mention:4"))

    def test_held_comment_for_step_resolves_the_row_and_none_for_an_absent_step(self):
        s = self.make_store()
        step = self._hold(s, "mention:1", 1.0)
        self.assertEqual(held_comment_for_step(s, step).key, "mention:1")
        self.assertIsNone(held_comment_for_step(s, "nope"))

    def test_seed_day_summary_claim_round_trips_through_summary_day_for_step(self):
        s = self.make_store()
        day = datetime.date(2026, 1, 1)
        s.mark_day_summary_dirty(day)
        seed_day_summary_claim(s, day, "step-1", 3)
        self.assertEqual(s.summary_day_for_step("step-1"), day)
        self.assertEqual(s.day_summary(day).spawn_count, 3)


class TestStoreSeedOnFakeStore(StoreSeedBase, unittest.TestCase):
    def make_store(self):
        return FakeStore(strict_shortcode=True)


class TestStoreSeedOnSqliteStore(StoreSeedBase, unittest.TestCase):
    def make_store(self):
        return make_sqlite_store()
