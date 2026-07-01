import datetime
import json
import unittest

from the_grid.application.feedback import (ReflectInput, ReflectUseCase, RetroInput, RetroUseCase,
                                           WorklogInput, WorklogUseCase)
from the_grid.application.services.flow import FlowService
from tests.support.fake_fs import FakeFs
from tests.support.fake_store import FakeStore

_METAS = {"reviewer": {"model": "opus", "step": "review", "signals": {"review_rounds": "rejected"}}}


def _flow(store):
    return FlowService(FakeFs(_METAS), store)


class TestReflect(unittest.TestCase):
    def test_records_reflection_on_the_task_with_spec_hash(self):
        s = FakeStore()
        story = s.create_story("st")
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


class TestRetro(unittest.TestCase):
    def test_gathers_feedback_and_signals(self):
        s = FakeStore()
        epic = s.create_story("epic")
        story = s.create_story("st", epic=epic)
        k = s.create_task("build: x", step="build", role="coder", parent=story)
        s.add_artifact(k, "reflection", json.dumps({"task": k, "feedback": "fb1", "spec_hash": "h"}))
        resp = RetroUseCase(s, _flow(s)).execute(RetroInput(epic=epic))
        self.assertEqual(resp.reflection_count, 1)
        self.assertEqual(resp.feedback[0].text, "fb1")
        self.assertEqual(len(resp.story_signals), 1)
        self.assertEqual(resp.story_signals[0].reflections, 1)

    def test_empty_when_no_reflections(self):
        s = FakeStore()
        epic = s.create_story("epic")
        s.create_story("st", epic=epic)
        resp = RetroUseCase(s, _flow(s)).execute(RetroInput(epic=epic))
        self.assertEqual(resp.reflection_count, 0)
        self.assertEqual(resp.feedback, [])


class TestWorklog(unittest.TestCase):
    def _now(self):
        n = datetime.datetime.now().astimezone()
        return n.date(), n.tzinfo

    def test_lists_stories_closed_in_period(self):
        s = FakeStore()
        sid = s.create_story("shipped story")
        s.close(sid, "merged")
        today, tz = self._now()
        resp = WorklogUseCase(s).execute(WorklogInput(period_args=[], today=today, tz=tz))
        self.assertIn(sid, [e.id for e in resp.entries])

    def test_empty_when_nothing_closed(self):
        s = FakeStore()
        s.create_story("still open")
        today, tz = self._now()
        resp = WorklogUseCase(s).execute(WorklogInput(period_args=[], today=today, tz=tz))
        self.assertEqual(resp.entries, [])


if __name__ == "__main__":
    unittest.main()
