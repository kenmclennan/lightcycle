import unittest

from lightcycle.domain.schedule.guards import guard_names, parse_guard_params
from lightcycle.domain.schedule.schedule import (
    SOURCE_BOTH,
    SOURCE_BUNDLE,
    SOURCE_CONFIG,
    merge_schedule,
)


def full_block(**overrides):
    base = {"enabled": "true", "workflow": "lightcycle/audit", "project": "acme/app",
            "cron": "0 9 * * 1", "guard": "materials-changed"}
    base.update(overrides)
    return base


class TestGuardSchemas(unittest.TestCase):
    def test_the_engine_has_exactly_four_guards(self):
        self.assertEqual(
            set(guard_names()),
            {"pending-reflections", "materials-changed", "day-unsummarised", "repos-active"})

    def test_an_unknown_guard_is_refused(self):
        with self.assertRaisesRegex(ValueError, "unknown guard"):
            parse_guard_params("run-shell", {})

    def test_an_unknown_parameter_is_refused(self):
        with self.assertRaisesRegex(ValueError, "no parameter"):
            parse_guard_params("materials-changed", {"min": "3"})

    def test_a_required_parameter_must_be_present_and_a_positive_integer(self):
        with self.assertRaisesRegex(ValueError, "needs parameter min"):
            parse_guard_params("pending-reflections", {})
        for bad in ("0", "-1", "two", "1.5", ""):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    parse_guard_params("pending-reflections", {"min": bad})
        self.assertEqual(parse_guard_params("pending-reflections", {"min": "30"}), {"min": 30})


class TestMergeSchedule(unittest.TestCase):
    def test_a_bare_suggestion_is_bundle_sourced_and_never_enabled(self):
        s = merge_schedule(
            "lightcycle/audit", None,
            {"cron": "0 9 * * 1", "guard": "materials-changed"}, workflow="lightcycle/audit")
        self.assertEqual((s.source, s.enabled, s.problem), (SOURCE_BUNDLE, False, None))

    def test_a_block_with_no_suggestion_is_config_sourced(self):
        s = merge_schedule("weekly", full_block(), None)
        self.assertEqual((s.source, s.enabled, s.problem), (SOURCE_CONFIG, True, None))

    def test_a_block_over_a_suggestion_is_both_and_overrides_field_by_field(self):
        s = merge_schedule(
            "weekly", full_block(cron="0 1 * * *", guard=None),
            {"cron": "0 9 * * 1", "guard": "pending-reflections", "min": "5"})
        self.assertEqual(s.source, SOURCE_BOTH)
        self.assertEqual(s.cron, "0 1 * * *")
        self.assertEqual(s.guard, "pending-reflections")
        self.assertEqual(s.params, {"min": 5})

    def test_enabled_false_is_explicitly_off(self):
        s = merge_schedule("weekly", full_block(enabled="off"), None)
        self.assertEqual((s.enabled, s.explicit_off), (False, True))

    def test_problems_are_reported_not_raised(self):
        cases = {
            "no enabled line": {k: v for k, v in full_block().items() if k != "enabled"},
            "bad enabled": full_block(enabled="maybe"),
            "no workflow": full_block(workflow=""),
            "no project": full_block(project=""),
            "no cron": full_block(cron=""),
            "no guard": full_block(guard=""),
            "bad cron": full_block(cron="@daily"),
            "bad guard": full_block(guard="shell"),
            "bad param": full_block(guard="pending-reflections", min="x"),
        }
        for label, block in cases.items():
            with self.subTest(label):
                self.assertIsNotNone(merge_schedule("weekly", block, None).problem)

    def test_labels_are_space_separated(self):
        self.assertEqual(
            merge_schedule("weekly", full_block(labels="a  b"), None).labels, ("a", "b"))

    def test_an_id_must_be_lowercase_words(self):
        self.assertIsNotNone(merge_schedule("Weekly_Audit", full_block(), None).problem)
