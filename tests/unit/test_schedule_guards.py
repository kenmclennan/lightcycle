import datetime
import unittest

from lightcycle.application.pool.schedule_guards import GuardUnreadable, ScheduleGuards
from lightcycle.domain.flow.flow import GUIDANCE_WORKSPACE
from tests.support.fake_git import FakeGit
from tests.support.fake_store import FakeStore
from tests.support.schedule_fakes import StubWorkflowSource

NOW = datetime.datetime(2026, 10, 14, 11, 0)


def close_with_reflections(store, id, count=1):
    item = store.create_item("work %s" % id, "d", id=id)
    for n in range(count):
        store.add_artifact(item, "reflection", "note %d" % n)
    store.complete_node(item, "merged")
    return item


def firing(store, state, created="2026-10-10T09:00:00"):
    item = store.create_item("prior", "d", shortcode="SCH")
    store._records[item]["created_at"] = created
    store.add_artifact(item, "schedule-state", state, internal=True)
    store.complete_node(item, "merged")
    return store.get_item(item)


def guards(store=None, git=None, source=None):
    store = store or FakeStore()
    return store, ScheduleGuards(
        store, git or FakeGit(), source or StubWorkflowSource(shas={"lightcycle": "sha1"}))


class TestPendingReflections(unittest.TestCase):
    def test_passes_exactly_at_the_minimum_and_not_below(self):
        store, g = guards()
        close_with_reflections(store, "LC-1", 2)

        below = g.evaluate("pending-reflections", {"min": 3}, [], NOW)
        close_with_reflections(store, "LC-2", 1)
        at_min = g.evaluate("pending-reflections", {"min": 3}, [], NOW)

        self.assertFalse(below.passed)
        self.assertTrue(at_min.passed)
        self.assertEqual(at_min.title, "Audit of 2 closed items, 0 closed passes")
        self.assertEqual(at_min.description, "batch: LC-1, LC-2")
        self.assertEqual(at_min.state, "batch: LC-1, LC-2")

    def test_ids_in_an_earlier_batch_are_not_counted_again(self):
        store, g = guards()
        close_with_reflections(store, "LC-1", 3)
        prior = firing(store, "batch: LC-1")

        result = g.evaluate("pending-reflections", {"min": 1}, [prior], NOW)

        self.assertFalse(result.passed)

    def test_a_new_close_after_an_earlier_batch_is_counted(self):
        store, g = guards()
        close_with_reflections(store, "LC-1", 3)
        prior = firing(store, "batch: LC-1")
        close_with_reflections(store, "LC-2", 1)

        result = g.evaluate("pending-reflections", {"min": 1}, [prior], NOW)

        self.assertTrue(result.passed)
        self.assertEqual(result.state, "batch: LC-2")


class TestMaterialsChanged(unittest.TestCase):
    def _guidance(self, store, git_sha="g1"):
        store.add_project(GUIDANCE_WORKSPACE, local_path="/tmp/g")
        return FakeGit(ref="origin/main", ref_shas={("/tmp/g", "origin/main"): git_sha})

    def test_passes_on_first_run_with_a_fingerprint_state(self):
        store, g = guards()

        result = g.evaluate("materials-changed", {}, [], NOW)

        self.assertTrue(result.passed)
        self.assertEqual(result.state, "lightcycle=sha1")
        self.assertIn("since: none", result.description)
        self.assertIn("previous: none", result.description)

    def test_does_not_pass_on_an_unchanged_fingerprint(self):
        store, g = guards()
        prior = firing(store, "lightcycle=sha1")

        self.assertFalse(g.evaluate("materials-changed", {}, [prior], NOW).passed)

    def test_passes_after_an_origin_sha_changes(self):
        store = FakeStore()
        prior = firing(store, "lightcycle=sha1")
        _, g = guards(store, source=StubWorkflowSource(shas={"lightcycle": "sha2"}))

        result = g.evaluate("materials-changed", {}, [prior], NOW)

        self.assertTrue(result.passed)
        self.assertIn("since: 2026-10-10", result.description)
        self.assertIn("previous: %s" % prior.id, result.description)

    def test_the_guidance_sha_is_part_of_the_fingerprint(self):
        store = FakeStore()
        git = self._guidance(store, "g1")
        _, g = guards(store, git)
        first = g.evaluate("materials-changed", {}, [], NOW)
        prior = firing(store, first.state)
        self.assertEqual(first.state, "guidance=g1;lightcycle=sha1")
        self.assertFalse(g.evaluate("materials-changed", {}, [prior], NOW).passed)

        git2 = self._guidance(store, "g2")
        _, g2 = guards(store, git2)
        self.assertTrue(g2.evaluate("materials-changed", {}, [prior], NOW).passed)

    def test_a_git_read_failure_is_unreadable_never_a_pass(self):
        store = FakeStore()
        git = self._guidance(store)
        git._raises = {"ref_sha"}
        _, g = guards(store, git)

        with self.assertRaises(GuardUnreadable):
            g.evaluate("materials-changed", {}, [], NOW)


class TestDayUnsummarised(unittest.TestCase):
    def _close(self, store, id, closed_at):
        item = store.create_item("work", "d", id=id)
        store.complete_node(item, "merged")
        store._records[item]["closed_at"] = closed_at

    def test_prefers_today_then_yesterday(self):
        store, g = guards()
        self._close(store, "LC-1", "2026-10-13T12:00:00+00:00")
        yesterday = g.evaluate("day-unsummarised", {}, [], NOW)
        self._close(store, "LC-2", "2026-10-14T09:00:00+00:00")
        today = g.evaluate("day-unsummarised", {}, [], NOW)

        self.assertEqual(yesterday.title, "Daily summary: 2026-10-13")
        self.assertEqual(today.title, "Daily summary: 2026-10-14")
        self.assertEqual(today.state, "day: 2026-10-14 count: 1")
        self.assertIn("LC-2 - work", today.description)

    def test_is_false_once_the_recorded_count_catches_up(self):
        store, g = guards()
        self._close(store, "LC-1", "2026-10-14T09:00:00+00:00")
        prior = firing(store, "day: 2026-10-14 count: 1")

        self.assertFalse(g.evaluate("day-unsummarised", {}, [prior], NOW).passed)

    def test_passes_again_when_more_closes_land_after_a_firing(self):
        store, g = guards()
        self._close(store, "LC-1", "2026-10-14T09:00:00+00:00")
        self._close(store, "LC-2", "2026-10-14T09:30:00+00:00")
        prior = firing(store, "day: 2026-10-14 count: 1")

        self.assertTrue(g.evaluate("day-unsummarised", {}, [prior], NOW).passed)

    def test_nothing_closed_is_false(self):
        _, g = guards()
        self.assertFalse(g.evaluate("day-unsummarised", {}, [], NOW).passed)


class TestUnknownGuard(unittest.TestCase):
    def test_an_unknown_guard_is_unreadable(self):
        _, g = guards()
        with self.assertRaises(GuardUnreadable):
            g.evaluate("shell", {}, [], NOW)
