import datetime
import json
import unittest

from the_grid.application.feedback import (
    ReflectInput,
    ReflectUseCase,
    RetroInput,
    RetroUseCase,
    WorklogInput,
    WorklogUseCase,
)
from the_grid.application.services.flow import FlowService
from the_grid.domain.feedback import UNLABELED_MODEL
from tests.support.fake_fs import FakeFs
from tests.support.fake_store import FakeStore

_METAS = {"reviewer": {"model": "opus", "step": "review", "signals": {"review_rounds": "rejected"}}}


def _flow(store):
    return FlowService(FakeFs(_METAS), store)


def _add_reflection(store, task_id, feedback):
    store.add_artifact(
        task_id, "reflection", json.dumps({"task": task_id, "feedback": feedback, "spec_hash": "h"})
    )


class TestReflect(unittest.TestCase):
    def test_records_reflection_on_the_task_with_spec_hash(self):
        s = FakeStore()
        story = s.create_story("st", epic=s.create_epic("epic"))
        s.add_artifact(story, "spec", "/specs/x.md")
        k = s.create_task("build: x", step="build", role="coder", parent=story)
        fs = FakeFs(files={"/specs/x.md": b"spec body"})
        resp = ReflectUseCase(s, fs).execute(ReflectInput(task=k, feedback="went well"))
        self.assertEqual(resp.reflection.task, k)
        refl = json.loads(s.story_artifacts(k)[0].value)
        self.assertEqual(refl["task"], k)
        self.assertEqual(refl["feedback"], "went well")
        self.assertNotEqual(refl["spec_hash"], "unknown")

    def test_unknown_spec_hash_when_no_spec(self):
        s = FakeStore()
        k = s.create_task("loose task", role="human")
        ReflectUseCase(s, FakeFs()).execute(ReflectInput(task=k, feedback="fb"))
        refl = json.loads(s.story_artifacts(k)[0].value)
        self.assertEqual(refl["spec_hash"], "unknown")


class TestRetroEpicScope(unittest.TestCase):
    def test_gathers_feedback_and_signals(self):
        s = FakeStore()
        epic = s.create_epic("epic")
        story = s.create_story("st", epic=epic)
        k = s.create_task("build: x", step="build", role="coder", parent=story)
        _add_reflection(s, k, "fb1")
        resp = RetroUseCase(s, _flow(s)).execute(RetroInput(subject=epic))
        self.assertEqual(resp.reflection_count, 1)
        self.assertEqual(resp.feedback[0].text, "fb1")
        self.assertEqual(len(resp.story_signals), 1)
        self.assertEqual(resp.story_signals[0].reflections, 1)

    def test_empty_when_no_reflections(self):
        s = FakeStore()
        epic = s.create_epic("epic")
        s.create_story("st", epic=epic)
        resp = RetroUseCase(s, _flow(s)).execute(RetroInput(subject=epic))
        self.assertEqual(resp.reflection_count, 0)
        self.assertEqual(resp.feedback, [])

    def test_subject_label_is_the_epic_id(self):
        s = FakeStore()
        epic = s.create_epic("epic")
        s.create_story("st", epic=epic)
        resp = RetroUseCase(s, _flow(s)).execute(RetroInput(subject=epic))
        self.assertEqual(resp.subject, epic)


class TestRetroStoryScope(unittest.TestCase):
    def test_story_scope_returns_single_row(self):
        s = FakeStore()
        story = s.create_story("standalone story", epic=s.create_epic("epic"))
        k = s.create_task("build: x", step="build", role="coder", parent=story)
        _add_reflection(s, k, "story feedback")
        resp = RetroUseCase(s, _flow(s)).execute(RetroInput(subject=story))
        self.assertEqual(resp.reflection_count, 1)
        self.assertEqual(resp.feedback[0].text, "story feedback")
        self.assertEqual(len(resp.story_signals), 1)
        self.assertEqual(resp.story_signals[0].story.id, story)
        self.assertEqual(resp.story_signals[0].reflections, 1)

    def test_story_scope_with_no_tasks(self):
        s = FakeStore()
        story = s.create_story("empty story", epic=s.create_epic("epic"))
        resp = RetroUseCase(s, _flow(s)).execute(RetroInput(subject=story))
        self.assertEqual(resp.reflection_count, 0)
        self.assertEqual(len(resp.story_signals), 1)
        self.assertEqual(resp.story_signals[0].story.id, story)

    def test_story_with_rejected_task_tallies_signal(self):
        s = FakeStore()
        story = s.create_story("story", epic=s.create_epic("epic"))
        k = s.create_task("review: x", step="review", role="reviewer", parent=story)
        s.close(k, "rejected")
        resp = RetroUseCase(s, _flow(s)).execute(RetroInput(subject=story))
        self.assertEqual(resp.story_signals[0].signals.get("review_rounds"), {UNLABELED_MODEL: 1})


class TestRetroSinceScope(unittest.TestCase):
    def test_since_aggregates_closed_tasks_across_stories(self):
        s = FakeStore()
        epic = s.create_epic("epic")
        story1 = s.create_story("story1", epic=epic)
        k1 = s.create_task("build: a", step="build", role="coder", parent=story1)
        s.close(k1, "done")
        _add_reflection(s, k1, "reflection from story1")

        story2 = s.create_story("story2", epic=epic)
        k2 = s.create_task("build: b", step="build", role="coder", parent=story2)
        s.close(k2, "done")
        _add_reflection(s, k2, "reflection from story2")

        resp = RetroUseCase(s, _flow(s)).execute(RetroInput(since="2020-01-01"))
        self.assertEqual(resp.reflection_count, 2)
        self.assertEqual(len(resp.story_signals), 2)
        story_ids = {row.story.id for row in resp.story_signals}
        self.assertIn(story1, story_ids)
        self.assertIn(story2, story_ids)

    def test_since_excludes_open_tasks(self):
        s = FakeStore()
        story = s.create_story("story", epic=s.create_epic("epic"))
        k = s.create_task("build: x", step="build", role="coder", parent=story)
        _add_reflection(s, k, "not closed yet")
        resp = RetroUseCase(s, _flow(s)).execute(RetroInput(since="2020-01-01"))
        self.assertEqual(resp.reflection_count, 0)

    def test_since_label_in_response(self):
        s = FakeStore()
        resp = RetroUseCase(s, _flow(s)).execute(RetroInput(since="2024-06-01"))
        self.assertEqual(resp.subject, "since:2024-06-01")

    def test_since_includes_epicless_story_task(self):
        s = FakeStore()
        story = s.create_story("epicless story", epic=s.create_epic("epic"))
        s._records[story]["parent"] = None
        k = s.create_task("build: x", role="coder", parent=story)
        s.close(k, "done")
        _add_reflection(s, k, "epicless fb")
        resp = RetroUseCase(s, _flow(s)).execute(RetroInput(since="2020-01-01"))
        self.assertEqual(resp.reflection_count, 1)


class TestRetroLastScope(unittest.TestCase):
    def _make_closed_epic(self, s, title):
        epic = s.create_epic(title)
        story = s.create_story("child of %s" % title, epic=epic)
        k = s.create_task("task", role="coder", parent=story)
        _add_reflection(s, k, "fb from %s" % title)
        s.close(epic, "merged")
        return epic

    def test_last_n_aggregates_exactly_n_closed_epics(self):
        s = FakeStore()
        self._make_closed_epic(s, "epic1")
        self._make_closed_epic(s, "epic2")
        self._make_closed_epic(s, "epic3")
        resp = RetroUseCase(s, _flow(s)).execute(RetroInput(last=2))
        self.assertEqual(resp.reflection_count, 2)
        self.assertEqual(len(resp.story_signals), 2)

    def test_last_1_gives_most_recent_epic(self):
        s = FakeStore()
        self._make_closed_epic(s, "older")
        self._make_closed_epic(s, "newer")
        resp = RetroUseCase(s, _flow(s)).execute(RetroInput(last=1))
        self.assertEqual(resp.reflection_count, 1)

    def test_last_label_in_response(self):
        s = FakeStore()
        resp = RetroUseCase(s, _flow(s)).execute(RetroInput(last=3))
        self.assertEqual(resp.subject, "last:3")

    def test_last_more_than_available_returns_all(self):
        s = FakeStore()
        self._make_closed_epic(s, "only epic")
        resp = RetroUseCase(s, _flow(s)).execute(RetroInput(last=5))
        self.assertEqual(resp.reflection_count, 1)


class TestWorklog(unittest.TestCase):
    def _now(self):
        n = datetime.datetime.now().astimezone()
        return n.date(), n.tzinfo

    def test_lists_stories_closed_in_period(self):
        s = FakeStore()
        sid = s.create_story("shipped story", epic=s.create_epic("epic"))
        s.close(sid, "merged")
        today, tz = self._now()
        resp = WorklogUseCase(s).execute(WorklogInput(period_args=[], today=today, tz=tz))
        self.assertIn(sid, [e.id for e in resp.entries])

    def test_empty_when_nothing_closed(self):
        s = FakeStore()
        s.create_story("still open", epic=s.create_epic("epic"))
        today, tz = self._now()
        resp = WorklogUseCase(s).execute(WorklogInput(period_args=[], today=today, tz=tz))
        self.assertEqual(resp.entries, [])


if __name__ == "__main__":
    unittest.main()
